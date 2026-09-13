from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from synthesis.models import ActivityReport, AuditEvent, ReportCard, ReportVersion, WeeklyReport
from synthesis.services import (
    DomainError,
    cancel_report_draft,
    close_cycle,
    create_activity,
    create_cycle,
    generate_draft,
    generate_pdf_version,
    remove_card,
    reopen_cycle,
    reopen_report_selection,
    restore_card,
    update_card,
    update_cycle_deadline,
    update_own_activity,
    update_report,
    update_section,
)

from .conftest import image_upload


@pytest.mark.django_db
def test_create_activity_derives_manager_and_area(manager, cycle):
    created = create_activity(
        actor=manager,
        data={
            "templateKey": "acao_evento",
            "title": "Oficina de boas práticas",
            "date": cycle.starts_at,
            "location": "Centro de capacitação",
            "summary": "Atividade realizada com participantes da área.",
            "result": "Participantes definiram melhorias de aplicação imediata.",
            "beneficiaries": "24 participantes",
            "evidence": "24 planos de melhoria elaborados",
            "nextStep": "Acompanhar os planos no próximo ciclo.",
            "internalNotes": "Contexto de apoio que não entra na síntese.",
            "cycleId": cycle.id,
        },
        photos=[image_upload()],
    )
    assert created.manager == manager
    assert created.area == manager.area
    assert created.photos.get().is_main is True
    assert created.template_key == "acao_evento"
    assert created.internal_notes == "Contexto de apoio que não entra na síntese."
    assert AuditEvent.objects.filter(action="activity.created", entity_id=str(created.id)).exists()


@pytest.mark.django_db
def test_closed_cycle_blocks_create(manager, cycle):
    cycle.status = "encerrada"
    cycle.save()
    with pytest.raises(DomainError, match="encerrado"):
        create_activity(
            actor=manager,
            data={
                "templateKey": "acao_evento",
                "title": "Oficina de boas práticas",
                "date": cycle.starts_at,
                "location": "Centro",
                "summary": "Descrição suficiente para validar o relato.",
                "result": "Resultado suficiente para validar o relato.",
                "beneficiaries": "Participantes",
                "evidence": "",
                "nextStep": "",
                "internalNotes": "",
                "cycleId": cycle.id,
            },
            photos=[image_upload()],
        )


@pytest.mark.django_db
def test_editor_manages_the_weekly_cycle_lifecycle(editor, cycle):
    closed = close_cycle(actor=editor, cycle=cycle)
    assert closed.status == "encerrada"

    starts_at = cycle.ends_at + timedelta(days=1)
    ends_at = starts_at + timedelta(days=4)
    deadline = timezone.now() + timedelta(days=4)
    created = create_cycle(
        actor=editor,
        label="Próxima semana",
        starts_at=starts_at,
        ends_at=ends_at,
        deadline=deadline,
    )
    assert created.status == "aberta"
    with pytest.raises(DomainError, match="ciclo ativo"):
        create_cycle(
            actor=editor,
            label="Ciclo concorrente",
            starts_at=starts_at,
            ends_at=ends_at,
            deadline=deadline,
        )

    changed = update_cycle_deadline(
        actor=editor,
        cycle=created,
        deadline=deadline + timedelta(hours=1),
    )
    assert changed.deadline == deadline + timedelta(hours=1)
    close_cycle(actor=editor, cycle=created)
    reopened = reopen_cycle(
        actor=editor,
        cycle=closed,
        reason="Correção solicitada pela gerência",
        new_deadline=timezone.now() + timedelta(days=1),
    )
    assert reopened.status == "reaberta"
    assert AuditEvent.objects.filter(action="cycle.created", entity_id=str(created.id)).exists()
    assert AuditEvent.objects.filter(action="cycle.closed", entity_id=str(created.id)).exists()
    assert AuditEvent.objects.filter(action="cycle.reopened", entity_id=str(cycle.id)).exists()


@pytest.mark.django_db
def test_activity_is_editable_only_by_owner_while_cycle_accepts_reports(activity, manager, other_manager):
    updated = update_own_activity(actor=manager, report=activity, changes={"title": "Título corrigido"})
    assert updated.title == "Título corrigido"
    with pytest.raises(DomainError, match="próprios"):
        update_own_activity(actor=other_manager, report=activity, changes={"title": "Tentativa externa"})
    activity.cycle.status = "encerrada"
    activity.cycle.save()
    with pytest.raises(DomainError, match="encerrado"):
        update_own_activity(actor=manager, report=activity, changes={"title": "Tarde demais"})


@pytest.mark.django_db
def test_draft_is_unique_and_idempotent(activity, editor):
    first = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    second = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    assert first.id == second.id
    assert first.sections.get().cards.count() == 1


@pytest.mark.django_db
def test_draft_selection_is_closed_after_creation(activity, editor, other_manager):
    other = ActivityReport.objects.create(
        title="Formação de professores",
        date=activity.date,
        location="Escola",
        summary="Atividade de formação realizada com professores da rede.",
        result="Professores criaram propostas para aplicação comunitária.",
        beneficiaries="20 professores",
        area=other_manager.area,
        manager=other_manager,
        cycle=activity.cycle,
    )
    generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    with pytest.raises(DomainError, match="seleção está fechada"):
        generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id, other.id])


@pytest.mark.django_db
def test_editorial_changes_never_change_original(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)
    update_card(actor=editor, card=card, changes={"editorialTitle": "Título editorial"})
    activity.refresh_from_db()
    assert activity.title == "Visita técnica aos produtores"
    assert ReportCard.objects.get(pk=card.pk).editorial_title == "Título editorial"


@pytest.mark.django_db
def test_draft_keeps_metadata_snapshot(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)
    assert card.original_location == activity.location
    assert card.original_beneficiaries == activity.beneficiaries
    assert card.original_manager_name == activity.manager.name


@pytest.mark.django_db
def test_draft_builds_editable_executive_briefing(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    assert "1 iniciativa" in report.executive_summary
    content_version = report.content_version

    report = update_report(
        actor=editor,
        report=report,
        executive_summary="A semana consolidou um avanço verificável no atendimento aos produtores.",
    )
    section = report.sections.get()
    report = update_section(
        actor=editor,
        section=section,
        executive_summary="A área concentrou esforços no acompanhamento técnico.",
    )

    assert report.executive_summary.startswith("A semana consolidou")
    assert report.sections.get().executive_summary.startswith("A área concentrou")
    assert report.content_version == content_version + 2


@pytest.mark.django_db
def test_draft_copies_publishable_template_fields_but_not_internal_notes(activity, editor):
    activity.evidence = "18 produtores orientados"
    activity.next_step = "Revisar os registros na próxima visita."
    activity.internal_notes = "Informação interna que não deve aparecer no card."
    activity.save()
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)

    assert card.editorial_evidence == activity.evidence
    assert card.editorial_next_step == activity.next_step
    assert activity.internal_notes not in {
        card.editorial_title,
        card.editorial_summary,
        card.editorial_result,
        card.editorial_evidence,
        card.editorial_next_step,
    }


@pytest.mark.django_db
def test_activity_template_rejects_oversized_publishable_text(manager, cycle):
    with pytest.raises(DomainError, match="no máximo 240"):
        create_activity(
            actor=manager,
            data={
                "templateKey": "acao_evento",
                "title": "Oficina de boas práticas",
                "date": cycle.starts_at,
                "location": "Centro",
                "summary": "a" * 241,
                "result": "Resultado suficiente para validar o relato.",
                "beneficiaries": "Participantes",
                "evidence": "",
                "nextStep": "",
                "internalNotes": "Os detalhes extensos podem ficar aqui.",
                "cycleId": cycle.id,
            },
            photos=[image_upload()],
        )


@pytest.mark.django_db
def test_remove_card_keeps_original(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)
    remove_card(actor=editor, card=card)
    assert ActivityReport.objects.filter(pk=activity.pk).exists()
    assert ReportCard.objects.get(pk=card.pk).removed is True


@pytest.mark.django_db
def test_editor_can_restore_removed_card_before_publication(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)
    remove_card(actor=editor, card=card)
    restored = restore_card(actor=editor, card=card)

    assert restored.sections.get().cards.get().removed is False
    assert AuditEvent.objects.filter(action="report.card_restored", entity_id=str(card.id)).exists()


@pytest.mark.django_db
def test_editor_can_reopen_replace_and_cancel_unpublished_draft(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = report.sections.get().cards.get()
    update_card(actor=editor, card=card, changes={"editorialTitle": "Título temporário"})

    reopened = reopen_report_selection(actor=editor, report=report)
    assert reopened.status == "em_selecao"
    replaced = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    assert replaced.id == report.id
    assert replaced.sections.get().cards.get().editorial_title == activity.title

    cancel_report_draft(actor=editor, report=replaced)
    assert not WeeklyReport.objects.filter(pk=report.pk).exists()


@pytest.mark.django_db
def test_published_report_blocks_destructive_recovery(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    generate_pdf_version(actor=editor, report_id=report.id)

    with pytest.raises(DomainError, match="primeira versão"):
        reopen_report_selection(actor=editor, report=report)
    with pytest.raises(DomainError, match="publicado"):
        cancel_report_draft(actor=editor, report=report)


@pytest.mark.django_db
def test_pdf_versions_are_incremental_and_immutable(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    first = generate_pdf_version(actor=editor, report_id=report.id)
    second = generate_pdf_version(actor=editor, report_id=report.id)
    assert (first.version, second.version) == (1, 2)
    assert first.pdf.name != second.pdf.name
    assert ReportVersion.objects.filter(weekly_report=report).count() == 2


@pytest.mark.django_db
def test_pdf_enforces_executive_briefing_rules(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = report.sections.get().cards.get()
    update_report(actor=editor, report=report, executive_summary="")
    with pytest.raises(DomainError, match="leitura executiva"):
        generate_pdf_version(actor=editor, report_id=report.id)

    report.refresh_from_db()
    update_report(actor=editor, report=report, executive_summary="A semana registrou avanço técnico.")
    update_card(
        actor=editor,
        card=card,
        changes={"executiveClassification": "destaque"},
    )
    with pytest.raises(DomainError, match="evidência"):
        generate_pdf_version(actor=editor, report_id=report.id)

    update_card(
        actor=editor,
        card=card,
        changes={
            "editorialEvidence": "18 produtores orientados",
            "editorialNextStep": "Acompanhar os registros de produção.",
            "nextStepOwner": "Gestor",
            "nextStepDueDate": activity.date + timedelta(days=7),
            "needsDecision": True,
        },
    )
    with pytest.raises(DomainError, match="pedido"):
        generate_pdf_version(actor=editor, report_id=report.id)

    update_card(
        actor=editor,
        card=card,
        changes={"decisionRequest": "Aprovar a agenda de acompanhamento."},
    )
    assert generate_pdf_version(actor=editor, report_id=report.id).version == 1


@pytest.mark.django_db
def test_pdf_requires_legacy_card_to_fit_editorial_budget(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)
    card.editorial_summary = "a" * 241
    card.save(update_fields=("editorial_summary", "updated_at"))

    with pytest.raises(DomainError, match="excede o limite"):
        generate_pdf_version(actor=editor, report_id=report.id)


@pytest.mark.django_db
def test_pdf_includes_the_selected_photo(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    version = generate_pdf_version(actor=editor, report_id=report.id)
    version.pdf.open("rb")
    try:
        content = version.pdf.read()
    finally:
        version.pdf.close()
    assert content.startswith(b"%PDF")
    assert b"/Subtype /Image" in content


@pytest.mark.django_db
def test_pdf_rejects_stale_snapshot(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])

    def edit_during_render(snapshot):
        WeeklyReport.objects.filter(pk=snapshot.pk).update(
            updated_at=snapshot.updated_at + timedelta(seconds=1),
            content_version=snapshot.content_version + 1,
        )
        return b"%PDF-stale"

    with patch("synthesis.services.render_report_pdf", side_effect=edit_during_render):
        with pytest.raises(DomainError, match="mudou durante"):
            generate_pdf_version(actor=editor, report_id=report.id)
    assert not ReportVersion.objects.filter(weekly_report=report).exists()


@pytest.mark.django_db
def test_pdf_storage_is_compensated_when_database_save_fails(activity, editor, settings):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    with patch.object(ReportVersion, "save", side_effect=OSError("database unavailable")):
        with pytest.raises(OSError):
            generate_pdf_version(actor=editor, report_id=report.id)
    assert not list(settings.MEDIA_ROOT.rglob("*.pdf"))

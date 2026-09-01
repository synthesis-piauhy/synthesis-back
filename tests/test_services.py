import pytest

from synthesis.models import ActivityReport, AuditEvent, ReportCard, ReportVersion
from synthesis.services import (
    DomainError,
    create_activity,
    generate_draft,
    generate_pdf_version,
    remove_card,
    update_card,
    update_own_activity,
)

from .conftest import image_upload


@pytest.mark.django_db
def test_create_activity_derives_manager_and_area(manager, cycle):
    created = create_activity(
        actor=manager,
        data={
            "title": "Oficina de boas práticas",
            "date": cycle.starts_at,
            "location": "Centro de capacitação",
            "summary": "Atividade realizada com participantes da área.",
            "result": "Participantes definiram melhorias de aplicação imediata.",
            "beneficiaries": "24 participantes",
            "cycleId": cycle.id,
        },
        photos=[image_upload()],
    )
    assert created.manager == manager
    assert created.area == manager.area
    assert created.photos.get().is_main is True
    assert AuditEvent.objects.filter(action="activity.created", entity_id=str(created.id)).exists()


@pytest.mark.django_db
def test_closed_cycle_blocks_create(manager, cycle):
    cycle.status = "encerrada"
    cycle.save()
    with pytest.raises(DomainError, match="encerrado"):
        create_activity(
            actor=manager,
            data={
                "title": "Oficina de boas práticas",
                "date": cycle.starts_at,
                "location": "Centro",
                "summary": "Descrição suficiente para validar o relato.",
                "result": "Resultado suficiente para validar o relato.",
                "beneficiaries": "Participantes",
                "cycleId": cycle.id,
            },
            photos=[image_upload()],
        )


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
def test_remove_card_keeps_original(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)
    remove_card(actor=editor, card=card)
    assert ActivityReport.objects.filter(pk=activity.pk).exists()
    assert ReportCard.objects.get(pk=card.pk).removed is True


@pytest.mark.django_db
def test_pdf_versions_are_incremental_and_immutable(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    first = generate_pdf_version(actor=editor, report_id=report.id)
    second = generate_pdf_version(actor=editor, report_id=report.id)
    assert (first.version, second.version) == (1, 2)
    assert first.pdf.name != second.pdf.name
    assert ReportVersion.objects.filter(weekly_report=report).count() == 2

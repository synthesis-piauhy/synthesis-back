from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch

import pytest
from django.db import connection, connections

from synthesis.models import ReportCard, ReportSection, ReportVersion, User, WeeklyReport
from synthesis.pdf import render_report_pdf as real_render_report_pdf
from synthesis.rate_limits import consume
from synthesis.services import (
    DomainError,
    create_activity,
    generate_draft,
    generate_pdf_version,
    reorder_cards,
    update_card,
)

from .conftest import image_upload


def run_isolated(function):
    connections.close_all()
    try:
        return function()
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_concurrent_draft_is_idempotent_on_postgres(activity, editor):
    if connection.vendor != "postgresql":
        pytest.skip("select_for_update requires PostgreSQL")
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=5)
        actor = User.objects.get(pk=editor.pk)
        return generate_draft(actor=actor, cycle_id=activity.cycle_id, activity_ids=[activity.id]).pk

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: run_isolated(create), range(2)))
    assert len(set(ids)) == 1
    assert WeeklyReport.objects.filter(cycle_id=activity.cycle_id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_pdf_versions_are_sequential_on_postgres(activity, editor):
    if connection.vendor != "postgresql":
        pytest.skip("select_for_update requires PostgreSQL")
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    barrier = Barrier(2)

    def synchronized_render(snapshot):
        content = real_render_report_pdf(snapshot)
        barrier.wait(timeout=10)
        return content

    def generate():
        actor = User.objects.get(pk=editor.pk)
        return generate_pdf_version(actor=actor, report_id=report.pk).version

    with patch("synthesis.services.render_report_pdf", side_effect=synchronized_render):
        with ThreadPoolExecutor(max_workers=2) as executor:
            versions = list(executor.map(lambda _: run_isolated(generate), range(2)))
    assert sorted(versions) == [1, 2]
    stored = ReportVersion.objects.filter(weekly_report=report).values_list("version", flat=True)
    assert list(stored) == [1, 2]


@pytest.mark.django_db(transaction=True)
def test_edit_during_pdf_rejects_stale_snapshot_on_postgres(activity, editor):
    if connection.vendor != "postgresql":
        pytest.skip("select_for_update requires PostgreSQL")
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    card = ReportCard.objects.get(section__weekly_report=report)
    rendering = Event()
    edited = Event()

    def paused_render(snapshot):
        content = real_render_report_pdf(snapshot)
        rendering.set()
        assert edited.wait(timeout=10)
        return content

    def generate():
        actor = User.objects.get(pk=editor.pk)
        return generate_pdf_version(actor=actor, report_id=report.pk)

    def edit():
        assert rendering.wait(timeout=10)
        actor = User.objects.get(pk=editor.pk)
        current = ReportCard.objects.select_related("section__weekly_report").get(pk=card.pk)
        update_card(actor=actor, card=current, changes={"editorialTitle": "Edição concorrente"})
        edited.set()

    with patch("synthesis.services.render_report_pdf", side_effect=paused_render):
        with ThreadPoolExecutor(max_workers=2) as executor:
            pdf_future = executor.submit(lambda: run_isolated(generate))
            edit_future = executor.submit(lambda: run_isolated(edit))
            edit_future.result(timeout=15)
            with pytest.raises(DomainError, match="mudou durante"):
                pdf_future.result(timeout=15)
    assert not ReportVersion.objects.filter(weekly_report=report).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_reorders_leave_one_complete_order_on_postgres(activity, manager, editor):
    if connection.vendor != "postgresql":
        pytest.skip("select_for_update requires PostgreSQL")
    second = create_activity(
        actor=manager,
        data={
            "templateKey": "acao_evento",
            "title": "Segunda atividade",
            "date": activity.date,
            "location": "Centro",
            "summary": "Segunda atividade usada para validar a ordenação concorrente.",
            "result": "A ordenação final permanece completa e consistente.",
            "beneficiaries": "Participantes",
            "evidence": "",
            "nextStep": "",
            "internalNotes": "",
            "cycleId": activity.cycle_id,
        },
        photos=[image_upload()],
    )
    report = generate_draft(
        actor=editor,
        cycle_id=activity.cycle_id,
        activity_ids=[activity.id, second.id],
    )
    section = ReportSection.objects.get(weekly_report=report)
    card_ids = list(section.cards.values_list("id", flat=True))
    permutations = [card_ids, list(reversed(card_ids))]
    barrier = Barrier(2)

    def reorder(order):
        barrier.wait(timeout=5)
        actor = User.objects.get(pk=editor.pk)
        current = ReportSection.objects.select_related("weekly_report").get(pk=section.pk)
        reorder_cards(actor=actor, section=current, card_ids=order)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda order: run_isolated(lambda: reorder(order)), permutations))
    stored = list(section.cards.order_by("order").values_list("id", flat=True))
    assert stored in permutations
    assert list(section.cards.order_by("order").values_list("order", flat=True)) == [0, 1]


@pytest.mark.django_db(transaction=True)
def test_rate_limit_is_atomic_across_connections_on_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("row locking requires PostgreSQL")
    workers = 10
    barrier = Barrier(workers)

    def attempt():
        barrier.wait(timeout=10)
        return consume("concurrent-test", "shared", 5, 60)

    with patch("synthesis.rate_limits.time.time", return_value=120):
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(lambda _: run_isolated(attempt), range(workers)))
    assert results.count(0) == 5
    assert all(result in {0, 60} for result in results)

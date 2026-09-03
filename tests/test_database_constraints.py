import pytest
from django.db import IntegrityError, transaction

from synthesis.models import Area, ReportCard, ReportVersion, User, UserRole, WeeklyCycle
from synthesis.services import generate_draft

pytestmark = pytest.mark.django_db


def raises_integrity_error(operation):
    with pytest.raises(IntegrityError), transaction.atomic():
        operation()


def test_area_name_is_unique_ignoring_case(area):
    raises_integrity_error(lambda: Area.objects.create(name=area.name.lower()))


def test_manager_requires_an_area():
    raises_integrity_error(
        lambda: User.objects.create(
            email="sem-area@synthesis.local",
            name="Gestor sem área",
            role=UserRole.MANAGER,
        )
    )


def test_role_and_status_values_are_protected(manager, cycle):
    raises_integrity_error(lambda: User.objects.filter(pk=manager.pk).update(role="papel-invalido"))
    raises_integrity_error(lambda: WeeklyCycle.objects.filter(pk=cycle.pk).update(status="invalido"))


def test_reopened_cycle_requires_reason(cycle):
    raises_integrity_error(
        lambda: WeeklyCycle.objects.filter(pk=cycle.pk).update(status="reaberta", reopen_reason="")
    )


def test_essential_activity_and_card_text_cannot_be_empty(activity, editor):
    raises_integrity_error(lambda: type(activity).objects.filter(pk=activity.pk).update(title=""))
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.pk])
    card = ReportCard.objects.get(section__weekly_report=report)
    raises_integrity_error(lambda: ReportCard.objects.filter(pk=card.pk).update(editorial_title=""))


def test_report_version_starts_at_one(activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.pk])
    raises_integrity_error(
        lambda: ReportVersion.objects.create(
            weekly_report=report,
            version=0,
            generated_by=editor,
            pdf="reports/invalid.pdf",
        )
    )

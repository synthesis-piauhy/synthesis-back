import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from synthesis.models import Notification
from synthesis.notifications import ensure_deadline_reminders
from synthesis.services import close_cycle, create_activity, reopen_cycle, update_cycle_deadline

from .conftest import image_upload


def client_for(user):
    client = Client()
    response = client.post(
        "/api/token/pair",
        data=json.dumps({"email": user.email, "password": "senha-forte-123"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    return client, {"HTTP_X_CSRFTOKEN": response.json()["csrfToken"]}


@pytest.mark.django_db
def test_existing_open_cycle_is_announced_once(manager, cycle):
    ensure_deadline_reminders(manager)
    ensure_deadline_reminders(manager)
    assert (
        Notification.objects.filter(user=manager, dedupe_key__startswith=f"cycle:current:{cycle.id}").count()
        == 1
    )


@pytest.mark.django_db
def test_cycle_events_and_deadline_reminder_are_targeted_and_idempotent(
    editor, manager, other_manager, cycle
):
    close_cycle(actor=editor, cycle=cycle)
    assert Notification.objects.filter(user=manager, kind="ciclo", message__contains="encerrado").exists()

    deadline = timezone.now() + timedelta(hours=12)
    reopened = reopen_cycle(actor=editor, cycle=cycle, reason="Prazo extraordinário", new_deadline=deadline)
    assert Notification.objects.filter(user=manager, kind="ciclo", message__contains="reaberto").count() == 1
    assert (
        Notification.objects.filter(user=other_manager, kind="ciclo", message__contains="reaberto").count()
        == 1
    )

    ensure_deadline_reminders(manager)
    ensure_deadline_reminders(manager)
    assert Notification.objects.filter(user=manager, dedupe_key__startswith="deadline:").count() == 1

    update_cycle_deadline(actor=editor, cycle=reopened, deadline=timezone.now() + timedelta(hours=18))
    assert Notification.objects.filter(user=manager, dedupe_key__startswith="deadline:").count() == 0
    assert Notification.objects.filter(user=manager, message__contains="mudou para").count() == 1


@pytest.mark.django_db
def test_completed_activity_notifies_manager_and_only_own_notifications_are_readable(
    manager, other_manager, cycle
):
    cycle.deadline = timezone.now() + timedelta(hours=12)
    cycle.save(update_fields=("deadline", "updated_at"))
    ensure_deadline_reminders(manager)
    assert Notification.objects.filter(user=manager, dedupe_key__startswith="deadline:").exists()
    report = create_activity(
        actor=manager,
        data={
            "templateKey": "acao_evento", "title": "Oficina de boas práticas", "date": cycle.starts_at,
            "location": "Centro", "summary": "Atividade realizada com participantes da área.",
            "result": "Participantes concluíram seus planos de melhoria.",
            "beneficiaries": "24 participantes", "cycleId": cycle.id,
        },
        photos=[image_upload()],
    )
    notice = Notification.objects.get(user=manager, dedupe_key=f"activity:created:{report.id}")
    assert notice.href == f"/relatos/{report.id}"
    assert not Notification.objects.filter(user=manager, dedupe_key__startswith="deadline:").exists()
    ensure_deadline_reminders(manager)
    assert not Notification.objects.filter(user=manager, dedupe_key__startswith="deadline:").exists()

    other_client, other_headers = client_for(other_manager)
    other_items = other_client.get("/api/notifications", **other_headers).json()["items"]
    assert all(item["id"] != str(notice.id) for item in other_items)
    assert other_client.patch(f"/api/notifications/{notice.id}/read", **other_headers).status_code == 404

    client, headers = client_for(manager)
    feed = client.get("/api/notifications", **headers)
    assert feed.status_code == 200
    assert feed.json()["unreadCount"] == 1
    assert feed.json()["items"][0]["href"] == f"/relatos/{report.id}"
    assert client.patch(f"/api/notifications/{notice.id}/read", **headers).json()["read"] is True
    assert client.get("/api/notifications", **headers).json()["unreadCount"] == 0
    assert client.post("/api/notifications/read-all", **headers).status_code == 200

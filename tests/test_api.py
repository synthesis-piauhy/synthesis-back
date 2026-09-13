import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from .conftest import image_upload


def authenticated_client(user, password="senha-forte-123"):
    client = Client()
    login = client.post(
        "/api/token/pair",
        data=json.dumps({"email": user.email, "password": password}),
        content_type="application/json",
    )
    assert login.status_code == 200
    return client, {"HTTP_X_CSRFTOKEN": login.json()["csrfToken"]}


@pytest.mark.django_db
def test_health_is_public():
    response = Client().get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"detail": "ok"}


@pytest.mark.django_db
def test_jwt_login_and_authenticated_user(manager):
    client, headers = authenticated_client(manager)
    response = client.get("/api/me", **headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(manager.id)


@pytest.mark.django_db
def test_manager_cannot_access_editorial_reports(manager):
    client, headers = authenticated_client(manager)
    response = client.get("/api/weekly-reports", **headers)
    assert response.status_code == 403


@pytest.mark.django_db
def test_manager_creates_activity_with_multipart_upload(manager, cycle):
    client, headers = authenticated_client(manager)
    response = client.post(
        "/api/activity-reports",
        data={
            "templateKey": "acao_evento",
            "title": "Oficina de boas práticas",
            "date": cycle.starts_at.isoformat(),
            "location": "Centro de capacitação",
            "summary": "Atividade realizada com participantes da área.",
            "result": "Participantes definiram melhorias para aplicação imediata.",
            "beneficiaries": "24 participantes",
            "evidence": "24 planos de melhoria elaborados",
            "nextStep": "Acompanhar os planos no próximo ciclo.",
            "internalNotes": "Detalhes disponíveis somente para conferência.",
            "cycleId": str(cycle.id),
            "photos": [image_upload()],
        },
        **headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["managerId"] == str(manager.id)
    assert body["area"] == manager.area.name
    assert body["photos"][0]["isMain"] is True
    assert body["templateKey"] == "acao_evento"
    assert body["evidence"] == "24 planos de melhoria elaborados"


@pytest.mark.django_db
def test_editor_generates_draft_through_api(editor, activity):
    client, headers = authenticated_client(editor)
    response = client.post(
        "/api/weekly-reports/draft",
        data=json.dumps({"cycleId": str(activity.cycle_id), "activityIds": [str(activity.id)]}),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 201
    assert response.json()["selectedActivityIds"] == [str(activity.id)]


@pytest.mark.django_db
def test_only_editor_or_admin_manages_cycles_through_operational_api(manager, editor, cycle):
    manager_client, manager_headers = authenticated_client(manager)
    assert manager_client.post(f"/api/cycles/{cycle.id}/close", **manager_headers).status_code == 403

    client, headers = authenticated_client(editor)
    response = client.post(f"/api/cycles/{cycle.id}/close", **headers)
    assert response.status_code == 200
    assert response.json()["status"] == "encerrada"

    starts_at = cycle.ends_at + timedelta(days=1)
    ends_at = starts_at + timedelta(days=4)
    deadline = timezone.now() + timedelta(days=4)
    response = client.post(
        "/api/cycles",
        data=json.dumps(
            {
                "label": "Próxima semana",
                "startsAt": starts_at.isoformat(),
                "endsAt": ends_at.isoformat(),
                "deadline": deadline.isoformat(),
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 201, response.content
    created_id = response.json()["id"]

    response = client.patch(
        f"/api/cycles/{created_id}/deadline",
        data=json.dumps({"deadline": (deadline + timedelta(hours=1)).isoformat()}),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200

    assert client.post(f"/api/cycles/{created_id}/close", **headers).status_code == 200
    response = client.post(
        f"/api/cycles/{cycle.id}/reopen",
        data=json.dumps(
            {
                "reason": "Correção operacional autorizada",
                "newDeadline": (timezone.now() + timedelta(days=1)).isoformat(),
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "reaberta"


@pytest.mark.django_db
def test_editor_updates_executive_briefing_through_api(editor, activity):
    client, headers = authenticated_client(editor)
    draft = client.post(
        "/api/weekly-reports/draft",
        data=json.dumps({"cycleId": str(activity.cycle_id), "activityIds": [str(activity.id)]}),
        content_type="application/json",
        **headers,
    ).json()
    report_id = draft["id"]
    response = client.patch(
        f"/api/weekly-reports/{report_id}",
        data=json.dumps({"executiveSummary": "A semana consolidou um avanço técnico verificável."}),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["executiveSummary"].startswith("A semana consolidou")

    section_id = draft["sections"][0]["id"]
    response = client.patch(
        f"/api/weekly-reports/{report_id}/sections/{section_id}",
        data=json.dumps({"executiveSummary": "A área avançou no atendimento técnico."}),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["sections"][0]["executiveSummary"].startswith("A área avançou")

    card_id = draft["sections"][0]["cards"][0]["id"]
    response = client.patch(
        f"/api/weekly-reports/{report_id}/cards/{card_id}",
        data=json.dumps({"executiveClassification": "atencao", "needsDecision": True}),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["executiveClassification"] == "atencao"
    assert response.json()["needsDecision"] is True


@pytest.mark.django_db
def test_editor_recovers_unpublished_report_through_api(editor, activity):
    client, headers = authenticated_client(editor)
    draft = client.post(
        "/api/weekly-reports/draft",
        data=json.dumps({"cycleId": str(activity.cycle_id), "activityIds": [str(activity.id)]}),
        content_type="application/json",
        **headers,
    ).json()
    report_id = draft["id"]
    card_id = draft["sections"][0]["cards"][0]["id"]

    removed = client.delete(f"/api/weekly-reports/{report_id}/cards/{card_id}", **headers)
    assert removed.status_code == 200
    assert removed.json()["sections"][0]["cards"][0]["removed"] is True
    restored = client.post(f"/api/weekly-reports/{report_id}/cards/{card_id}/restore", **headers)
    assert restored.status_code == 200
    assert restored.json()["sections"][0]["cards"][0]["removed"] is False

    reopened = client.post(f"/api/weekly-reports/{report_id}/selection/reopen", **headers)
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "em_selecao"
    cancelled = client.delete(f"/api/weekly-reports/{report_id}", **headers)
    assert cancelled.status_code == 200
    assert cancelled.json() == {"detail": "Rascunho cancelado."}


@pytest.mark.django_db
def test_openapi_schema_is_available():
    response = Client().get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/activity-reports" in paths
    assert "/api/weekly-reports/draft" in paths
    assert "/api/weekly-reports/{report_id}/selection/reopen" in paths


@pytest.mark.django_db
def test_paginated_lists_are_bounded(manager):
    client, headers = authenticated_client(manager)
    response = client.get("/api/cycles?page=1&pageSize=1", **headers)
    assert response.status_code == 200
    assert set(response.json()) == {"items", "total", "page", "pageSize"}
    assert response.json()["pageSize"] == 1
    assert client.get("/api/cycles?pageSize=101", **headers).status_code == 400

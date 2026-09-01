import json

import pytest
from django.test import Client

from .conftest import image_upload


def authenticated_client(user, password="senha-forte-123"):
    client = Client()
    login = client.post(
        "/api/token/pair",
        data=json.dumps({"email": user.email, "password": password}),
        content_type="application/json",
    )
    assert login.status_code == 200
    return client, {"HTTP_AUTHORIZATION": f"Bearer {login.json()['access']}"}


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
            "title": "Oficina de boas práticas",
            "date": cycle.starts_at.isoformat(),
            "location": "Centro de capacitação",
            "summary": "Atividade realizada com participantes da área.",
            "result": "Participantes definiram melhorias para aplicação imediata.",
            "beneficiaries": "24 participantes",
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
def test_openapi_schema_is_available():
    response = Client().get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/activity-reports" in paths
    assert "/api/weekly-reports/draft" in paths

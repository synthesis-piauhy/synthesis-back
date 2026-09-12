import json

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client

from .test_api import authenticated_client

pytestmark = pytest.mark.django_db


def test_csrf_login_mutation_and_logout(manager):
    client = Client(enforce_csrf_checks=True)
    payload = json.dumps({"email": manager.email, "password": "senha-forte-123"})
    assert client.post("/api/token/pair", payload, content_type="application/json").status_code == 403
    token = client.get("/api/token/csrf").json()["csrfToken"]
    response = client.post(
        "/api/token/pair", payload, content_type="application/json", HTTP_X_CSRFTOKEN=token
    )
    assert response.status_code == 200
    assert "access" not in response.json() and "refresh" not in response.json()
    assert response.cookies[settings.SESSION_COOKIE_NAME]["httponly"]
    stolen = client.cookies[settings.SESSION_COOKIE_NAME].value
    assert client.post("/api/token/logout").status_code == 403
    assert (
        client.patch(
            "/api/activity-reports/00000000-0000-0000-0000-000000000000",
            "{}",
            content_type="application/json",
        ).status_code
        == 403
    )
    csrf = response.json()["csrfToken"]
    assert client.post("/api/token/logout", HTTP_X_CSRFTOKEN=csrf).status_code == 200
    assert not Session.objects.filter(session_key=stolen).exists()
    attacker = Client()
    attacker.cookies[settings.SESSION_COOKIE_NAME] = stolen
    assert attacker.get("/api/me").status_code == 401
    assert client.post("/api/token/logout", HTTP_X_CSRFTOKEN=csrf).status_code == 200


def test_global_logout_password_and_deactivation_revoke_sessions(manager):
    first, headers = authenticated_client(manager)
    second, _ = authenticated_client(manager)
    assert first.post("/api/token/logout-all", **headers).status_code == 200
    assert second.get("/api/me").status_code == 401
    third, _ = authenticated_client(manager)
    manager.refresh_from_db()
    manager.set_password("Outra-senha-segura-123")
    manager.save()
    assert third.get("/api/me").status_code == 401
    fourth, _ = authenticated_client(manager, "Outra-senha-segura-123")
    manager.active = False
    manager.save()
    manager.active = True
    manager.save()
    assert fourth.get("/api/me").status_code == 401


def test_legacy_bearer_tokens_no_longer_authenticate(manager):
    assert Client().get("/api/me", HTTP_AUTHORIZATION="Bearer legacy-token").status_code == 401

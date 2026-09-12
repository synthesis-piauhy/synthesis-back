import json

import pytest
from django.test import Client

from synthesis.models import RateWindow
from synthesis.rate_limits import consume


@pytest.mark.django_db
def test_limit_shared_across_clients_and_accounts(monkeypatch):
    monkeypatch.setattr("synthesis.rate_limits.time.time", lambda: 120)
    for _ in range(10):
        response = Client().post(
            "/api/token/pair",
            json.dumps({"email": "missing@example.org", "password": "bad"}),
            content_type="application/json",
        )
        assert response.status_code == 401
    response = Client().post(
        "/api/token/pair",
        json.dumps({"email": " MISSING@example.org ", "password": "bad"}),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.1",
    )
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0
    assert all("missing" not in key for key in RateWindow.objects.values_list("key", flat=True))


@pytest.mark.django_db
def test_counter_resets_in_next_window(monkeypatch):
    monkeypatch.setattr("synthesis.rate_limits.time.time", lambda: 120)
    assert consume("test", "one", 1) == 0
    assert consume("test", "one", 1) == 60
    monkeypatch.setattr("synthesis.rate_limits.time.time", lambda: 180)
    assert consume("test", "one", 1) == 0

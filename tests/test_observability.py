from uuid import UUID

import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_readiness_and_request_id():
    response = Client().get("/api/health/ready", HTTP_X_REQUEST_ID="invalid")
    assert response.status_code == 200
    assert response["X-Request-ID"]
    UUID(response["X-Request-ID"])

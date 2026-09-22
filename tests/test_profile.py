import json
from io import BytesIO
from urllib.parse import urlparse

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from synthesis.models import AuditEvent, User

from .conftest import image_upload
from .test_api import authenticated_client


@pytest.mark.django_db
def test_user_can_change_only_own_name_and_cannot_edit_login_email_or_area(manager, other_manager):
    client, headers = authenticated_client(manager)
    response = client.patch(
        "/api/me",
        data=json.dumps({"name": "  Novo   Nome  "}),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Novo Nome"
    assert response.json()["email"] == manager.email
    assert response.json()["area"] == manager.area.name
    manager.refresh_from_db()
    assert manager.name == "Novo Nome"
    assert AuditEvent.objects.filter(actor=manager, action="profile.name_updated").exists()
    assert client.get("/api/me", **headers).json()["name"] == "Novo Nome"

    forged = client.patch(
        "/api/me",
        data=json.dumps(
            {
                "name": "Nome Falso",
                "email": other_manager.email,
                "area": other_manager.area.name,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert forged.status_code == 422
    manager.refresh_from_db()
    assert manager.name == "Novo Nome"
    assert manager.email != other_manager.email
    assert manager.area_id != other_manager.area_id
    anonymous = Client().patch(
        "/api/me", data=json.dumps({"name": "Invasor"}), content_type="application/json"
    )
    assert anonymous.status_code == 401


@pytest.mark.django_db(transaction=True)
def test_avatar_is_normalized_private_replaced_and_removed(manager, other_manager, settings):
    client, headers = authenticated_client(manager)
    response = client.post("/api/me/avatar", data={"avatar": image_upload("primeira.png")}, **headers)
    assert response.status_code == 200, response.content
    first_url = response.json()["avatarUrl"]
    assert first_url
    manager.refresh_from_db()
    first_name = manager.avatar.name
    assert first_name.endswith(".jpg") and "primeira" not in first_name
    first_file = settings.MEDIA_ROOT / first_name
    assert first_file.exists()

    path = urlparse(first_url).path
    assert Client().get(path).status_code == 401
    outsider, _ = authenticated_client(other_manager)
    assert outsider.get(path).status_code == 404
    image_response = client.get(first_url)
    assert image_response.status_code == 200
    assert image_response["Content-Type"] == "image/jpeg"
    assert image_response["Cache-Control"] == "private, no-store"
    with Image.open(BytesIO(b"".join(image_response.streaming_content))) as image:
        assert image.format == "JPEG"

    invalid = client.post(
        "/api/me/avatar",
        data={"avatar": SimpleUploadedFile("falsa.png", b"<script>bad</script>", content_type="image/png")},
        **headers,
    )
    assert invalid.status_code == 400
    manager.refresh_from_db()
    assert manager.avatar.name == first_name

    replacement = client.post("/api/me/avatar", data={"avatar": image_upload("segunda.png")}, **headers)
    assert replacement.status_code == 200
    assert replacement.json()["avatarUrl"] != first_url
    manager.refresh_from_db()
    second_name = manager.avatar.name
    assert second_name != first_name
    assert not first_file.exists()
    assert (settings.MEDIA_ROOT / second_name).exists()

    removed = client.delete("/api/me/avatar", **headers)
    assert removed.status_code == 200
    assert removed.json()["avatarUrl"] is None
    manager.refresh_from_db()
    assert not manager.avatar
    assert not (settings.MEDIA_ROOT / second_name).exists()
    assert client.get(path).status_code == 404
    assert User.objects.get(pk=manager.pk).email == manager.email

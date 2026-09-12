import pytest
from django.test import Client

from synthesis.services import generate_draft, generate_pdf_version

from .test_api import authenticated_client

pytestmark = pytest.mark.django_db


def test_private_photo_permissions_and_legacy_path(activity, manager, other_manager, editor):
    photo = activity.photos.get()
    url = f"/api/files/photos/{photo.id}"
    assert Client().get(url).status_code == 401
    assert Client().get(photo.image.url).status_code == 404
    outsider, _ = authenticated_client(other_manager)
    assert outsider.get(url).status_code == 404
    for user in (manager, editor):
        client, _ = authenticated_client(user)
        response = client.get(url)
        assert response.status_code == 200
        assert response["Content-Type"] == "image/jpeg"
        assert response["Cache-Control"] == "private, no-store"
        assert b"".join(response.streaming_content).startswith(b"\xff\xd8")


def test_pdf_download_requires_editorial_or_admin_permission(activity, manager, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.id])
    version = generate_pdf_version(actor=editor, report_id=report.id)
    url = f"/api/files/versions/{version.id}"
    assert Client().get(url).status_code == 401
    client, _ = authenticated_client(manager)
    assert client.get(url).status_code == 403
    client, _ = authenticated_client(editor)
    response = client.get(url)
    assert response.status_code == 200
    assert b"".join(response.streaming_content).startswith(b"%PDF")

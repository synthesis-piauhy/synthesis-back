from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from synthesis.models import ActivityPhoto, ActivityReport
from synthesis.services import DomainError, create_activity
from synthesis.validators import normalize_image

from .conftest import image_upload
from .test_api import authenticated_client


def payload(cycle):
    return dict(
        title="Oficina comunitária",
        date=cycle.starts_at,
        location="Centro",
        summary="Descrição da oficina comunitária.",
        result="Resultado da oficina comunitária.",
        beneficiaries="24 participantes",
        cycleId=cycle.id,
    )


@pytest.mark.django_db
def test_forged_upload_rejected_by_api_and_model(manager, cycle, activity, settings):
    client, headers = authenticated_client(manager)

    def forged():
        return SimpleUploadedFile(
            "proof.html", b"<html><script>alert(1)</script></html>", content_type="image/jpeg"
        )

    before = ActivityReport.objects.count()
    data = payload(cycle)
    data["cycleId"] = str(cycle.id)
    response = client.post("/api/activity-reports", data={**data, "photos": [forged()]}, **headers)
    assert response.status_code == 400
    assert ActivityReport.objects.count() == before
    photo = ActivityPhoto(activity_report=activity, image=forged(), name="forged")
    with pytest.raises(ValidationError):
        photo.full_clean()
    with pytest.raises(ValidationError):
        photo.save()
    assert not list(settings.MEDIA_ROOT.rglob("*.html"))


@pytest.mark.parametrize("fmt,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_valid_images_are_reencoded(fmt, mime):
    data = BytesIO()
    Image.new("RGB", (10, 8), "red").save(data, format=fmt)
    normalized = normalize_image(SimpleUploadedFile("unsafe.html", data.getvalue(), content_type=mime))
    assert normalized.name.endswith(".jpg") and "unsafe" not in normalized.name
    with Image.open(normalized) as result:
        assert result.format == "JPEG"
        assert result.size == (10, 8)
        assert not result.getexif()


def test_mismatch_truncation_and_pixel_limit():
    wrong = image_upload()
    wrong.content_type = "image/jpeg"
    with pytest.raises(ValidationError):
        normalize_image(wrong)
    with pytest.raises(ValidationError):
        normalize_image(SimpleUploadedFile("broken.png", b"\x89PNG\r\n", content_type="image/png"))
    with patch("synthesis.validators.MAX_IMAGE_PIXELS", 1), pytest.raises(ValidationError):
        normalize_image(image_upload())


@pytest.mark.django_db
def test_storage_failure_compensates_prior_upload(manager, cycle, settings):
    original = ActivityPhoto.save
    calls = 0

    def fail_second(photo, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("storage unavailable")
        return original(photo, *args, **kwargs)

    with patch.object(ActivityPhoto, "save", fail_second), pytest.raises(OSError):
        create_activity(actor=manager, data=payload(cycle), photos=[image_upload(), image_upload()])
    assert not ActivityReport.objects.exists()
    assert not list(settings.MEDIA_ROOT.rglob("*.jpg"))


@pytest.mark.django_db
def test_batch_is_validated_before_persistence(manager, cycle):
    with pytest.raises(DomainError):
        create_activity(
            actor=manager,
            data=payload(cycle),
            photos=[image_upload(), SimpleUploadedFile("bad.jpg", b"bad", content_type="image/jpeg")],
        )
    assert not ActivityReport.objects.exists()


@pytest.mark.django_db
def test_saved_upload_is_marked_as_normalized(manager, cycle):
    report = create_activity(actor=manager, data=payload(cycle), photos=[image_upload("original.png")])
    photo = report.photos.get()
    assert photo.is_normalized is True
    assert photo.name == "original.png"
    assert photo.image.name.endswith(".jpg")

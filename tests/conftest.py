from datetime import date, timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from synthesis.models import ActivityPhoto, ActivityReport, Area, User, UserRole, WeeklyCycle


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def area(db):
    return Area.objects.create(name="Agro", order=0)


@pytest.fixture
def other_area(db):
    return Area.objects.create(name="Educação", order=1)


@pytest.fixture
def manager(area):
    return User.objects.create_user(
        email="gestor@synthesis.local",
        password="senha-forte-123",
        name="Gestor",
        role=UserRole.MANAGER,
        area=area,
    )


@pytest.fixture
def other_manager(other_area):
    return User.objects.create_user(
        email="outro@synthesis.local",
        password="senha-forte-123",
        name="Outro gestor",
        role=UserRole.MANAGER,
        area=other_area,
    )


@pytest.fixture
def editor(area):
    return User.objects.create_user(
        email="gerente@synthesis.local",
        password="senha-forte-123",
        name="Gerente",
        role=UserRole.EDITOR,
        area=area,
    )


@pytest.fixture
def cycle(db):
    today = date.today()
    return WeeklyCycle.objects.create(
        label="Semana atual",
        starts_at=today - timedelta(days=2),
        ends_at=today + timedelta(days=2),
        deadline=timezone.now() + timedelta(days=2),
        status="aberta",
    )


def image_upload(name="foto.png"):
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def activity(manager, cycle):
    report = ActivityReport.objects.create(
        title="Visita técnica aos produtores",
        date=date.today(),
        location="Zona rural",
        summary="Acompanhamento técnico realizado com produtores locais.",
        result="Os participantes definiram melhorias para a próxima semana.",
        beneficiaries="18 produtores",
        area=manager.area,
        manager=manager,
        cycle=cycle,
    )
    ActivityPhoto.objects.create(
        activity_report=report,
        image=image_upload(),
        name="foto.png",
        alt="Visita técnica",
        is_main=True,
    )
    return report

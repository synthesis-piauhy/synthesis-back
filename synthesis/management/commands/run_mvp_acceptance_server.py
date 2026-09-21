import os
from datetime import date, timedelta
from io import BytesIO
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.core.management.commands.runserver import Command as RunserverCommand
from django.db import connection
from django.utils import timezone
from PIL import Image

from synthesis.models import ActivityPhoto, ActivityReport, Area, User, UserRole, WeeklyCycle

ACCEPTANCE_DATABASE = "synthesis_mvp_e2e"
PASSWORD = "Mvp-acceptance-749!"


def png_bytes(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format="PNG")
    return output.getvalue()


class Command(RunserverCommand):
    help = "Prepara dados descartáveis e inicia o backend do aceite integrado do MVP."

    def handle(self, *args, **options):
        database = connection.settings_dict
        if (
            settings.APP_ENV != "test"
            or connection.vendor != "postgresql"
            or database["NAME"] != ACCEPTANCE_DATABASE
            or database["HOST"] not in {"127.0.0.1", "localhost"}
            or str(database["PORT"]) != "5434"
            or os.getenv("ALLOW_MVP_ACCEPTANCE_RESET") != "true"
        ):
            raise CommandError(
                "Recusado: use APP_ENV=test, o PostgreSQL descartável "
                f"{ACCEPTANCE_DATABASE} em 127.0.0.1:5434 e ALLOW_MVP_ACCEPTANCE_RESET=true."
            )

        call_command("migrate", interactive=False, verbosity=0)
        call_command("flush", interactive=False, verbosity=0)

        agro = Area.objects.create(id=UUID("00000000-0000-0000-0000-000000000101"), name="Agro", order=0)
        Area.objects.create(id=UUID("00000000-0000-0000-0000-000000000102"), name="Educação", order=1)
        User.objects.create_user(
            id=UUID("00000000-0000-0000-0000-000000000201"),
            email="gestor.mvp@example.test",
            password=PASSWORD,
            name="Gestor MVP",
            role=UserRole.MANAGER,
            area=agro,
        )
        other_manager = User.objects.create_user(
            id=UUID("00000000-0000-0000-0000-000000000202"),
            email="outro.mvp@example.test",
            password=PASSWORD,
            name="Outro Gestor MVP",
            role=UserRole.MANAGER,
            area=agro,
        )
        User.objects.create_user(
            id=UUID("00000000-0000-0000-0000-000000000203"),
            email="gerente.mvp@example.test",
            password=PASSWORD,
            name="Gerente MVP",
            role=UserRole.EDITOR,
        )
        User.objects.create_superuser(
            id=UUID("00000000-0000-0000-0000-000000000204"),
            email="admin.mvp@example.test",
            password=PASSWORD,
            name="Administrador MVP",
        )

        today = date.today()
        cycle = WeeklyCycle.objects.create(
            id=UUID("00000000-0000-0000-0000-000000000301"),
            label="Ciclo de aceite do MVP",
            starts_at=today - timedelta(days=3),
            ends_at=today + timedelta(days=3),
            deadline=timezone.now() + timedelta(days=3),
            status="aberta",
        )
        activity = ActivityReport.objects.create(
            id=UUID("00000000-0000-0000-0000-000000000401"),
            template_key="acao_evento",
            title="Relato protegido de outro gestor",
            date=today,
            location="Unidade de demonstração",
            summary="Relato criado para validar autorização entre gestores.",
            result="A separação entre responsáveis foi verificada.",
            beneficiaries="12 participantes",
            evidence="Lista de presença conferida",
            next_step="",
            area=agro,
            manager=other_manager,
            cycle=cycle,
        )
        photo = ActivityPhoto(
            id=UUID("00000000-0000-0000-0000-000000000501"),
            activity_report=activity,
            name="aceite.png",
            alt="Imagem do relato protegido",
            is_main=True,
            is_normalized=False,
        )
        photo.image.save("aceite.png", ContentFile(png_bytes("blue")), save=True)

        self.stdout.write(self.style.SUCCESS("Base descartável do aceite do MVP preparada."))
        super().handle(*args, **options)

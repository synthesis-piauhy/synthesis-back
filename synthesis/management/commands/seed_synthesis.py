from django.core.management.base import BaseCommand

from synthesis.models import Area

AREAS = [
    "Agro",
    "Gastronomia",
    "Indústria e Móveis",
    "Moda",
    "Educação",
    "Jornadas Empresariais",
]


class Command(BaseCommand):
    help = "Cria ou atualiza as áreas iniciais da plataforma synthesis."

    def handle(self, *args, **options):
        for order, name in enumerate(AREAS):
            Area.objects.update_or_create(name=name, defaults={"order": order, "active": True})
        self.stdout.write(self.style.SUCCESS(f"{len(AREAS)} áreas disponíveis."))

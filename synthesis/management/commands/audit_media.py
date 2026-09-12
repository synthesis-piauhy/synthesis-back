from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from synthesis.validators import normalize_image


class Command(BaseCommand):
    help = "Inventaria imagens antigas suspeitas sem modificar ou excluir arquivos."

    def add_arguments(self, parser):
        parser.add_argument("--path", type=Path, default=Path(settings.MEDIA_ROOT) / "activities")

    def handle(self, *args, **options):
        root = options["path"].resolve()
        if not root.exists():
            self.stdout.write("Diretório de imagens não existe; nenhum arquivo encontrado.")
            return
        total = suspicious = 0
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            total += 1
            reasons = []
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                reasons.append("extensão não permitida")
            try:
                with path.open("rb") as stream:
                    normalize_image(File(stream, name=path.name))
            except Exception as error:
                reasons.append(f"conteúdo inválido: {error}")
            if reasons:
                suspicious += 1
                self.stdout.write(f"SUSPEITO {path.relative_to(root)} — {'; '.join(reasons)}")
        self.stdout.write(f"Analisados: {total}; suspeitos: {suspicious}; nenhuma alteração realizada.")

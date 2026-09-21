from uuid import UUID

from django.core.exceptions import ValidationError
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from ninja.errors import HttpError
from ninja_extra import api_controller, http_get

from .models import ActivityPhoto, ReportVersion, UserRole
from .validators import normalize_image


def private_response(file, *, content_type, filename, attachment=False):
    response = FileResponse(file, content_type=content_type, filename=filename, as_attachment=attachment)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@api_controller("/files", tags=["private files"])
class FileController:
    @http_get("/avatar")
    def avatar(self, request):
        if not request.user.avatar:
            raise HttpError(404, "Foto de perfil indisponível.")
        try:
            file = request.user.avatar.open("rb")
        except OSError as exc:
            raise HttpError(404, "Foto de perfil indisponível.") from exc
        return private_response(file, content_type="image/jpeg", filename="perfil.jpg")

    @http_get("/photos/{photo_id}")
    def photo(self, request, photo_id: UUID):
        photos = ActivityPhoto.objects.all()
        if request.user.role == UserRole.MANAGER:
            photos = photos.filter(activity_report__manager=request.user)
        photo = get_object_or_404(photos, pk=photo_id)
        try:
            if photo.is_normalized:
                safe = photo.image.open("rb")
            else:
                # Legacy files are decoded before serving until the audited migration is applied.
                with photo.image.open("rb") as source:
                    safe = normalize_image(source)
        except (ValidationError, OSError) as exc:
            raise HttpError(404, "Imagem indisponível.") from exc
        return private_response(safe, content_type="image/jpeg", filename=f"{photo.id}.jpg")

    @http_get("/versions/{version_id}")
    def pdf(self, request, version_id: UUID):
        if request.user.role not in {UserRole.EDITOR, UserRole.ADMIN}:
            raise HttpError(403, "Acesso restrito.")
        version = get_object_or_404(ReportVersion, pk=version_id)
        try:
            file = version.pdf.open("rb")
        except OSError as exc:
            raise HttpError(404, "PDF indisponível.") from exc
        return private_response(
            file, content_type="application/pdf", filename=f"relatorio-v{version.version}.pdf"
        )

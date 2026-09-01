from django.core.exceptions import ValidationError

MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def validate_image_size(image) -> None:
    if image.size > MAX_IMAGE_SIZE:
        raise ValidationError("A imagem deve ter no máximo 5 MB.")


def validate_image_content_type(image) -> None:
    content_type = getattr(image.file, "content_type", None)
    if content_type and content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("Use uma imagem JPEG, PNG ou WebP.")

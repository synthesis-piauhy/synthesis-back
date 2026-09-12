import warnings
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
IMAGE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_DIMENSION = 10_000
MAX_PHOTOS = 10
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def normalize_image(upload):
    """Decode untrusted bytes and return a new, metadata-free, server-named image."""
    if getattr(upload, "_synthesis_normalized", False):
        return upload
    validate_image_size(upload)
    try:
        upload.seek(0)
        # Bound reads even for file-like objects with an incorrect declared size.
        raw = upload.read(MAX_IMAGE_SIZE + 1)
        if len(raw) > MAX_IMAGE_SIZE:
            raise ValidationError("A imagem deve ter no máximo 5 MB.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as probe:
                content_type = getattr(upload, "content_type", None)
                if probe.format not in IMAGE_FORMATS:
                    raise ValidationError("Use imagens JPEG, PNG ou WebP.")
                if content_type and content_type != IMAGE_FORMATS[probe.format]:
                    raise ValidationError("O tipo informado não corresponde à imagem.")
                if max(probe.size) > MAX_IMAGE_DIMENSION or probe.width * probe.height > MAX_IMAGE_PIXELS:
                    raise ValidationError("A imagem possui dimensões excessivas.")
                if getattr(probe, "n_frames", 1) != 1:
                    raise ValidationError("Imagens animadas não são permitidas.")
                probe.verify()
            with Image.open(BytesIO(raw)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                rgba = oriented.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                output = BytesIO()
                clean.save(output, format="JPEG", quality=90)
        if output.tell() > MAX_IMAGE_SIZE:
            raise ValidationError("A imagem normalizada excede 5 MB; reduza suas dimensões.")
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValidationError("O arquivo não contém uma imagem válida.") from exc
    finally:
        upload.seek(0)
    result = ContentFile(output.getvalue(), name=f"{uuid4()}.jpg")
    result._synthesis_normalized = True
    result._synthesis_original_name = getattr(upload, "name", "imagem")
    return result


def validate_image_size(image) -> None:
    if image.size > MAX_IMAGE_SIZE:
        raise ValidationError("A imagem deve ter no máximo 5 MB.")


def validate_image_content_type(image) -> None:
    # Model.full_clean() must inspect bytes as well as ModelForm uploads.
    if not getattr(image, "_committed", False):
        normalize_image(getattr(image, "file", image))

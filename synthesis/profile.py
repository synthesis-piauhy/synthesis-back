from django.core.exceptions import ValidationError
from django.db import transaction

from .models import User
from .services import DomainError, audit
from .validators import normalize_image


def update_name(*, actor: User, name: str) -> User:
    normalized = " ".join(name.split())
    if not 2 <= len(normalized) <= 150:
        raise DomainError("Informe um nome entre 2 e 150 caracteres.")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=actor.pk)
        if user.name != normalized:
            user.name = normalized
            user.full_clean(exclude=("avatar",))
            user.save(update_fields=("name",))
            audit(user, "profile.name_updated", user)
    return user


def replace_avatar(*, actor: User, upload) -> User:
    try:
        normalized = normalize_image(upload)
    except ValidationError as exc:
        raise DomainError(" ".join(exc.messages)) from exc
    new_name = ""
    storage = None
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=actor.pk)
            old_name = user.avatar.name
            storage = user.avatar.storage
            user.avatar.save(normalized.name, normalized, save=False)
            new_name = user.avatar.name
            user.save(update_fields=("avatar",))
            audit(user, "profile.avatar_updated", user)
            if old_name:
                transaction.on_commit(lambda: storage.delete(old_name), robust=True)
    except Exception:
        if storage and new_name:
            storage.delete(new_name)
        raise
    return user


def remove_avatar(*, actor: User) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=actor.pk)
        if user.avatar:
            old_name = user.avatar.name
            storage = user.avatar.storage
            user.avatar = ""
            user.save(update_fields=("avatar",))
            audit(user, "profile.avatar_removed", user)
            transaction.on_commit(lambda: storage.delete(old_name), robust=True)
    return user

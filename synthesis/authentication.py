import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.db.models import F
from django.dispatch import receiver
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from ninja.security import SessionAuth

from .models import User


@receiver(user_logged_in)
def stamp_session(sender, request, user, **kwargs):
    request.session["synthesis_version"] = user.session_version


class BrowserSessionAuth(SessionAuth):
    def authenticate(self, request, key):
        user = super().authenticate(request, key)
        return user if user and user.active else None


class SessionVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and (
            not request.user.active
            or request.session.get("synthesis_version") != request.user.session_version
        ):
            logout(request)
        return self.get_response(request)


@never_cache
@require_GET
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


@never_cache
@require_POST
@csrf_protect
def login_view(request):
    try:
        payload = json.loads(request.body)
        email, password = payload["email"], payload["password"]
        if (
            not isinstance(email, str)
            or not isinstance(password, str)
            or len(email) > 254
            or len(password) > 1024
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Informe e-mail e senha válidos."}, status=400)
    user = authenticate(request, email=email.strip().lower(), password=password)
    if user is None:
        return JsonResponse({"detail": "E-mail ou senha inválidos."}, status=401)
    with transaction.atomic():
        current = User.objects.select_for_update().get(pk=user.pk)
        if not current.active or current.password != user.password:
            return JsonResponse({"detail": "E-mail ou senha inválidos."}, status=401)
        login(request, current, backend="django.contrib.auth.backends.ModelBackend")
        request.session.set_expiry(7 * 24 * 60 * 60)
    return JsonResponse({"detail": "Autenticado.", "csrfToken": get_token(request)})


@never_cache
@require_POST
@csrf_protect
def verify_session(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Sessão expirada. Entre novamente."}, status=401)
    return JsonResponse({"detail": "Sessão válida."})


@never_cache
@require_POST
@csrf_protect
def logout_view(request):
    logout(request)
    return JsonResponse({"detail": "Sessão encerrada."})


@never_cache
@require_POST
@csrf_protect
def logout_all_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Autenticação necessária."}, status=401)
    User.objects.filter(pk=request.user.pk).update(session_version=F("session_version") + 1)
    logout(request)
    return JsonResponse({"detail": "Todas as sessões foram encerradas."})

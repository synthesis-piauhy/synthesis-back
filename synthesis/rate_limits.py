import json
import time
from datetime import UTC, datetime

from django.conf import settings
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.utils.crypto import salted_hmac

from .models import RateWindow

_last_cleanup = 0


def consume(scope, identity, limit, period=60):
    """A bounded fixed window shared by every worker, serialized by the database."""
    global _last_cleanup
    now = int(time.time())
    if now - _last_cleanup >= 300:
        RateWindow.objects.filter(expires_at__lt=datetime.fromtimestamp(now, UTC)).delete()
        _last_cleanup = now
    window = now // period
    key = salted_hmac("synthesis-rate-limit", f"{scope}:{identity}:{window}", algorithm="sha256").hexdigest()
    expires = (window + 1) * period
    with transaction.atomic():
        bucket, _ = RateWindow.objects.get_or_create(
            key=key, defaults={"expires_at": datetime.fromtimestamp(expires, UTC)}
        )
        bucket = RateWindow.objects.select_for_update().get(pk=bucket.pk)
        if bucket.count >= limit:
            return max(1, expires - now)
        bucket.count += 1
        bucket.save(update_fields=["count"])
    return 0


def request_limits(request):
    ip = request.META.get("REMOTE_ADDR", "unknown")
    if settings.TRUST_PROXY:
        ip = request.META.get("HTTP_X_REAL_IP", ip)
    if request.path.startswith("/api/token/") or request.path == "/admin/login/":
        if request.method != "POST":
            return []
        limits = [("auth-ip", ip, 120, 60)]
        if request.path == "/api/token/pair":
            if len(request.body) > 8192:
                return [("oversize-login", ip, 0, 60)]
            try:
                email = str(json.loads(request.body).get("email", "")).strip().casefold()[:254]
            except (ValueError, AttributeError, UnicodeDecodeError):
                email = "invalid"
            limits.extend([("login-ip", ip, 30, 60), ("login-account", email, 10, 60)])
        return limits
    if request.method == "POST" and request.user.is_authenticated:
        identity = str(request.user.pk)
        if request.path == "/api/activity-reports":
            return [("upload", identity, 10, 60)]
        if request.path.startswith("/api/weekly-reports/") and request.path.endswith("/versions"):
            return [("pdf", identity, 3, 60)]
    return []


class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            for args in request_limits(request):
                retry = consume(*args)
                if retry:
                    response = JsonResponse(
                        {"detail": "Muitas solicitações. Aguarde e tente novamente."}, status=429
                    )
                    response["Retry-After"] = str(retry)
                    return response
        except DatabaseError:
            return JsonResponse({"detail": "Serviço temporariamente indisponível."}, status=503)
        return self.get_response(request)

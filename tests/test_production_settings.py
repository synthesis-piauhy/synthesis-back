import json
import os
import subprocess
import sys


def production_env(**changes):
    return {
        "PATH": os.environ["PATH"],
        "APP_ENV": "production",
        "DEBUG": "false",
        "SECRET_KEY": "ci-Django-A9b8C7d6E5f4G3h2I1j0K9l8M7n6O5p4Q3r2S1t0U9v8",
        "DATABASE_URL": "postgresql://ci:ci@localhost/ci?sslmode=verify-full",
        "ALLOWED_HOSTS": "synthesis.example.org",
        "PUBLIC_ORIGIN": "https://synthesis.example.org",
        **changes,
    }


def test_production_check_and_fail_closed():
    command = [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"]
    good = subprocess.run(command, env=production_env(), capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    for changes in (
        {"SECRET_KEY": ""},
        {"DEBUG": "true"},
        {"DATABASE_URL": "sqlite:///db.sqlite3"},
        {"ALLOWED_HOSTS": "*"},
        {"PUBLIC_ORIGIN": "http://example.org"},
    ):
        bad = subprocess.run(command, env=production_env(**changes), capture_output=True, text=True)
        assert bad.returncode != 0


def test_public_https_preview_uses_secure_cookies_and_trusts_only_its_origin():
    origin = "https://synthesis-preview.example.workers.dev"
    env = production_env(
        APP_ENV="development",
        DJANGO_SETTINGS_MODULE="config.settings",
        SYNTHESIS_PUBLIC_PREVIEW="true",
        PUBLIC_ORIGIN=origin,
        ALLOWED_HOSTS="127.0.0.1,localhost",
    )
    command = [
        sys.executable,
        "-c",
        "import json; from django.conf import settings; print(json.dumps({"
        "'debug': settings.DEBUG, 'session': settings.SESSION_COOKIE_SECURE, "
        "'csrf': settings.CSRF_COOKIE_SECURE, 'trusted': settings.CSRF_TRUSTED_ORIGINS, "
        "'cors': settings.CORS_ALLOWED_ORIGINS}))",
    ]
    good = subprocess.run(command, env=env, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout) == {
        "debug": False,
        "session": True,
        "csrf": True,
        "trusted": [origin],
        "cors": [origin],
    }
    for changes in (
        {"DEBUG": "true"},
        {"PUBLIC_ORIGIN": "http://example.workers.dev"},
        {"SECRET_KEY": "weak"},
    ):
        bad = subprocess.run(command, env={**env, **changes}, capture_output=True, text=True)
        assert bad.returncode != 0

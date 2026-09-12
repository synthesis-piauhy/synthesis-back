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

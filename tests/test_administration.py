import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, Permission
from django.utils import timezone

from synthesis.administration import RESOURCES
from synthesis.models import Area, AuditEvent, User, WeeklyCycle
from synthesis.services import generate_draft, generate_pdf_version

from .test_api import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(
        email="admin@synthesis.local", password="senha-forte-123", name="Administrador"
    )


def call(user, method, path, values=None):
    client, headers = authenticated_client(user)
    return getattr(client, method)(
        f"/api/administration/{path}",
        data=json.dumps({"values": values}) if values is not None else "",
        content_type="application/json",
        **headers,
    )


def user_values(user, **changes):
    return {
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "area": str(user.area_id) if user.area_id else "",
        "active": user.active,
        "password": "",
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "groups": [],
        "user_permissions": [],
        **changes,
    }


def test_every_resource_has_list_and_detail_without_secrets(admin_user, activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.pk])
    generate_pdf_version(actor=editor, report_id=report.pk)
    Group.objects.create(name="Consulta")
    client, headers = authenticated_client(admin_user)
    response = client.get("/api/administration/resources", **headers)
    assert response.status_code == 200, response.content
    assert {item["key"] for item in response.json()} == set(RESOURCES)
    for resource in RESOURCES:
        response = client.get(f"/api/administration/{resource}", **headers)
        assert response.status_code == 200, (resource, response.content)
        for item in response.json()["items"]:
            detail = client.get(f"/api/administration/{resource}/{item['id']}", **headers)
            assert detail.status_code == 200, (resource, detail.content)
            assert "password" not in detail.json()["values"]
            assert "pbkdf2" not in detail.content.decode()
    assert client.get("/api/administration/unknown", **headers).status_code == 404
    assert client.get("/api/administration/users/not-a-uuid", **headers).status_code == 404


@pytest.mark.parametrize("fixture", ["manager", "editor"])
def test_non_admin_cannot_read_or_mutate_administration(request, fixture):
    user = request.getfixturevalue(fixture)
    client, headers = authenticated_client(user)
    assert client.get("/api/administration/resources", **headers).status_code == 403
    assert client.get("/api/administration/users", **headers).status_code == 403
    assert call(user, "post", "areas", {"name": "Nova", "order": 1, "active": True}).status_code == 403


def test_area_crud_search_and_protected_delete(admin_user, manager):
    response = call(admin_user, "post", "areas", {"name": "Pesquisa", "order": 7, "active": False})
    assert response.status_code == 201, response.content
    area_id = response.json()["id"]
    response = call(
        admin_user, "put", f"areas/{area_id}", {"name": "Pesquisa e inovação", "order": 8, "active": True}
    )
    assert response.status_code == 200
    client, headers = authenticated_client(admin_user)
    response = client.get("/api/administration/areas?q=inova", **headers)
    assert response.json()["total"] == 1
    assert call(admin_user, "delete", f"areas/{manager.area_id}").status_code == 409
    assert call(admin_user, "delete", f"areas/{area_id}").status_code == 200
    assert not Area.objects.filter(pk=area_id).exists()
    assert AuditEvent.objects.filter(action="admin.areas.deleted", entity_id=area_id).exists()


def test_users_password_assignment_preservation_and_permissions(admin_user, area):
    permission = Permission.objects.get(codename="view_area")
    group = Group.objects.create(name="Consulta de áreas")
    response = call(
        admin_user,
        "post",
        "users",
        {
            "name": "Pessoa nova",
            "email": "nova@synthesis.local",
            "role": "gestor",
            "area": str(area.pk),
            "active": True,
            "password": "Nova-senha-segura-749!",
            "is_staff": True,
            "is_superuser": False,
            "groups": [str(group.pk)],
            "user_permissions": [str(permission.pk)],
        },
    )
    assert response.status_code == 201, response.content
    user = User.objects.get(pk=response.json()["id"])
    assert user.check_password("Nova-senha-segura-749!")
    assert user.groups.filter(pk=group.pk).exists()
    assert user.user_permissions.filter(pk=permission.pk).exists()
    response = call(admin_user, "put", f"users/{user.pk}", user_values(user, name="Nome alterado"))
    assert response.status_code == 200, response.content
    user.refresh_from_db()
    assert user.check_password("Nova-senha-segura-749!")
    response = call(
        admin_user, "put", f"users/{user.pk}", user_values(user, password="Outra-senha-segura-862!")
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password("Outra-senha-segura-862!")
    assert not user.check_password("Nova-senha-segura-749!")
    assert "Outra-senha" not in json.dumps(list(AuditEvent.objects.values_list("metadata", flat=True)))
    response = call(admin_user, "put", f"users/{user.pk}", user_values(user, active=False))
    assert response.status_code == 200
    user.refresh_from_db()
    assert not user.is_active


def test_user_validation_self_protection_and_privilege_escalation(admin_user, manager, activity):
    invalid = user_values(manager, area="", password="123")
    assert call(admin_user, "put", f"users/{manager.pk}", invalid).status_code == 400
    assert (
        call(admin_user, "put", f"users/{manager.pk}", user_values(manager, role="gerente")).status_code
        == 400
    )
    assert (
        call(admin_user, "put", f"users/{admin_user.pk}", user_values(admin_user, active=False)).status_code
        == 409
    )
    assert call(admin_user, "delete", f"users/{admin_user.pk}").status_code == 409
    normal_admin = User.objects.create_user(
        email="admin-comum@synthesis.local", password="senha-forte-123", name="Admin comum", role="admin"
    )
    assert call(normal_admin, "put", f"users/{admin_user.pk}", user_values(admin_user)).status_code == 403
    escalation = user_values(normal_admin, is_superuser=True)
    assert call(normal_admin, "put", f"users/{normal_admin.pk}", escalation).status_code == 400
    assert call(normal_admin, "post", "groups", {"name": "Novo", "permissions": []}).status_code == 403


def test_group_permissions_create_update_delete(admin_user):
    permission = Permission.objects.get(codename="view_area")
    response = call(admin_user, "post", "groups", {"name": "Leitura", "permissions": [str(permission.pk)]})
    assert response.status_code == 201, response.content
    group = Group.objects.get(pk=response.json()["id"])
    assert group.permissions.filter(pk=permission.pk).exists()
    response = call(admin_user, "put", f"groups/{group.pk}", {"name": "Consulta", "permissions": []})
    assert response.status_code == 200
    assert not group.permissions.exists()
    admin_user.groups.add(group)
    assert call(admin_user, "delete", f"groups/{group.pk}").status_code == 409
    admin_user.groups.clear()
    assert call(admin_user, "delete", f"groups/{group.pk}").status_code == 200


def test_cycle_create_close_reopen_and_protect_activity_dates(admin_user, activity):
    cycle = activity.cycle
    values = {
        "label": "Novo ciclo",
        "starts_at": cycle.starts_at.isoformat(),
        "ends_at": cycle.ends_at.isoformat(),
        "deadline": (timezone.now() + timedelta(days=3)).isoformat(),
        "status": "aberta",
        "reopen_reason": "",
    }
    response = call(admin_user, "post", "cycles", values)
    assert response.status_code == 201, response.content
    new_id = response.json()["id"]
    assert call(admin_user, "put", f"cycles/{new_id}", {**values, "status": "encerrada"}).status_code == 200
    assert WeeklyCycle.objects.get(pk=new_id).status == "encerrada"
    assert call(admin_user, "put", f"cycles/{new_id}", {**values, "status": "reaberta"}).status_code == 400
    response = call(
        admin_user,
        "put",
        f"cycles/{new_id}",
        {**values, "status": "reaberta", "reopen_reason": "Correções autorizadas"},
    )
    assert response.status_code == 200, response.content
    assert (
        call(
            admin_user,
            "put",
            f"cycles/{cycle.pk}",
            {**values, "ends_at": (cycle.starts_at - timedelta(days=1)).isoformat()},
        ).status_code
        == 400
    )
    assert call(admin_user, "delete", f"cycles/{cycle.pk}").status_code == 409
    assert call(admin_user, "delete", f"cycles/{new_id}").status_code == 200


def test_domain_and_history_resources_are_read_only(admin_user, activity, editor):
    report = generate_draft(actor=editor, cycle_id=activity.cycle_id, activity_ids=[activity.pk])
    version = generate_pdf_version(actor=editor, report_id=report.pk)
    assert call(admin_user, "put", f"versions/{version.pk}", {"version": 99}).status_code == 403
    assert call(admin_user, "delete", f"versions/{version.pk}").status_code == 403
    assert call(admin_user, "post", "audit", {"action": "forged"}).status_code == 403
    assert call(admin_user, "delete", f"activities/{activity.pk}").status_code == 403

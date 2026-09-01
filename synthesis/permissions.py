from ninja_extra import permissions

from .models import UserRole


class RolePermission(permissions.BasePermission):
    allowed_roles: set[str] = set()

    def has_permission(self, request, controller) -> bool:
        return bool(
            request.user.is_authenticated and request.user.active and request.user.role in self.allowed_roles
        )


class ManagerOnly(RolePermission):
    allowed_roles = {UserRole.MANAGER}


class EditorOnly(RolePermission):
    allowed_roles = {UserRole.EDITOR}


class AdminOnly(RolePermission):
    allowed_roles = {UserRole.ADMIN}


class EditorOrAdmin(RolePermission):
    allowed_roles = {UserRole.EDITOR, UserRole.ADMIN}

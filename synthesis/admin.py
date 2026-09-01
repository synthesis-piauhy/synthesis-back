from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    ActivityPhoto,
    ActivityReport,
    Area,
    AuditEvent,
    ReportCard,
    ReportSection,
    ReportVersion,
    User,
    WeeklyCycle,
    WeeklyReport,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "name", "role", "area", "active", "is_staff")
    list_filter = ("role", "active", "is_staff")
    search_fields = ("email", "name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Perfil", {"fields": ("name", "role", "area", "active")}),
        ("Permissões", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "role", "area", "password1", "password2", "is_staff"),
            },
        ),
    )


admin.site.register(Area)
admin.site.register(WeeklyCycle)
admin.site.register(ActivityReport)
admin.site.register(ActivityPhoto)
admin.site.register(WeeklyReport)
admin.site.register(ReportSection)
admin.site.register(ReportCard)
admin.site.register(ReportVersion)
admin.site.register(AuditEvent)

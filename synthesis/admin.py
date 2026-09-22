from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from . import notifications
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


@admin.register(WeeklyCycle)
class WeeklyCycleAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        previous = (
            WeeklyCycle.objects.filter(pk=obj.pk).values("status", "deadline").first() if change else None
        )
        super().save_model(request, obj, form, change)
        notifications.cycle_changed(request.user, obj, previous)


admin.site.register(ActivityReport)
admin.site.register(ActivityPhoto)


class DerivedReportAdmin(admin.ModelAdmin):
    """Mosaicos e seus artefatos só podem ser alterados pelo fluxo editorial."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(WeeklyReport, DerivedReportAdmin)
admin.site.register(ReportSection, DerivedReportAdmin)
admin.site.register(ReportCard, DerivedReportAdmin)
admin.site.register(ReportVersion, DerivedReportAdmin)
admin.site.register(AuditEvent, DerivedReportAdmin)

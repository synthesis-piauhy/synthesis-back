import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .managers import UserManager
from .validators import validate_image_content_type, validate_image_size


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Area(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("order", "name")

    def __str__(self) -> str:
        return self.name


class UserRole(models.TextChoices):
    MANAGER = "gestor", "Gestor"
    EDITOR = "gerente", "Gerente"
    ADMIN = "admin", "Administrador técnico"


class User(AbstractUser):
    username = None
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.MANAGER)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    active = models.BooleanField(default=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    objects = UserManager()

    class Meta:
        ordering = ("name", "email")

    def clean(self) -> None:
        super().clean()
        if self.role == UserRole.MANAGER and not self.area_id:
            raise ValidationError({"area": "Um gestor precisa pertencer a uma área."})

    def save(self, *args, **kwargs):
        self.is_active = self.active
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name or self.email


class CollectionStatus(models.TextChoices):
    OPEN = "aberta", "Aberta"
    CLOSED = "encerrada", "Encerrada"
    REOPENED = "reaberta", "Reaberta"


class WeeklyCycle(TimestampedModel):
    label = models.CharField(max_length=120)
    starts_at = models.DateField()
    ends_at = models.DateField()
    deadline = models.DateTimeField()
    status = models.CharField(max_length=16, choices=CollectionStatus.choices, default=CollectionStatus.OPEN)
    reopen_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-starts_at",)
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gte=models.F("starts_at")), name="cycle_dates_valid"),
        ]

    @property
    def accepts_reports(self) -> bool:
        return self.status in {CollectionStatus.OPEN, CollectionStatus.REOPENED}

    def __str__(self) -> str:
        return self.label


class ActivityReport(TimestampedModel):
    title = models.CharField(max_length=200)
    date = models.DateField()
    location = models.CharField(max_length=200)
    summary = models.TextField()
    result = models.TextField()
    beneficiaries = models.CharField(max_length=240)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="activity_reports")
    manager = models.ForeignKey(User, on_delete=models.PROTECT, related_name="activity_reports")
    cycle = models.ForeignKey(WeeklyCycle, on_delete=models.PROTECT, related_name="activity_reports")

    class Meta:
        ordering = ("-date", "-created_at")

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.manager_id and self.manager.role != UserRole.MANAGER:
            errors["manager"] = "O responsável pelo relato precisa ser um gestor."
        if self.manager_id and self.area_id and self.manager.area_id != self.area_id:
            errors["area"] = "A área do relato precisa ser a área do gestor."
        if self.cycle_id and not self.cycle.accepts_reports:
            errors["cycle"] = "O ciclo não aceita relatos."
        if self.cycle_id and not self.cycle.starts_at <= self.date <= self.cycle.ends_at:
            errors["date"] = "A data da atividade deve pertencer ao ciclo informado."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return self.title


class ActivityPhoto(TimestampedModel):
    activity_report = models.ForeignKey(ActivityReport, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(
        upload_to="activities/%Y/%m/",
        validators=[validate_image_size, validate_image_content_type],
    )
    name = models.CharField(max_length=255)
    is_main = models.BooleanField(default=False)
    alt = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-is_main", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("activity_report",),
                condition=Q(is_main=True),
                name="one_main_photo_per_activity",
            )
        ]

    def __str__(self) -> str:
        return self.name


class ReportStatus(models.TextChoices):
    NOT_STARTED = "nao_iniciado", "Não iniciado"
    SELECTING = "em_selecao", "Em seleção"
    DRAFT = "rascunho", "Rascunho"
    EDITING = "em_edicao", "Em edição"
    PDF_GENERATED = "pdf_gerado", "PDF gerado"


class WeeklyReport(TimestampedModel):
    cycle = models.OneToOneField(WeeklyCycle, on_delete=models.PROTECT, related_name="weekly_report")
    status = models.CharField(max_length=20, choices=ReportStatus.choices, default=ReportStatus.DRAFT)
    selected_activities = models.ManyToManyField(ActivityReport, related_name="weekly_reports", blank=True)

    class Meta:
        ordering = ("-cycle__starts_at",)

    def __str__(self) -> str:
        return f"Relatório — {self.cycle.label}"


class ReportSection(TimestampedModel):
    weekly_report = models.ForeignKey(WeeklyReport, on_delete=models.CASCADE, related_name="sections")
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="report_sections")
    title = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("order",)
        constraints = [
            models.UniqueConstraint(fields=("weekly_report", "area"), name="one_section_per_area_report")
        ]

    def __str__(self) -> str:
        return f"{self.weekly_report} — {self.title}"


class ReportCard(TimestampedModel):
    section = models.ForeignKey(ReportSection, on_delete=models.CASCADE, related_name="cards")
    activity_report = models.ForeignKey(ActivityReport, on_delete=models.PROTECT, related_name="report_cards")
    editorial_title = models.CharField(max_length=200)
    editorial_summary = models.TextField()
    editorial_result = models.TextField()
    selected_photo = models.ForeignKey(ActivityPhoto, on_delete=models.PROTECT, related_name="report_cards")
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="report_cards")
    original_date = models.DateField()
    order = models.PositiveSmallIntegerField(default=0)
    removed = models.BooleanField(default=False)

    class Meta:
        ordering = ("order",)
        constraints = [
            models.UniqueConstraint(fields=("section", "activity_report"), name="one_activity_per_section"),
        ]

    def __str__(self) -> str:
        return self.editorial_title

    def clean(self) -> None:
        super().clean()
        if self.selected_photo_id and self.activity_report_id:
            if self.selected_photo.activity_report_id != self.activity_report_id:
                raise ValidationError({"selected_photo": "A foto deve pertencer ao relato original."})


class ReportVersion(TimestampedModel):
    weekly_report = models.ForeignKey(WeeklyReport, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="generated_report_versions")
    pdf = models.FileField(upload_to="reports/%Y/%m/")

    class Meta:
        ordering = ("version",)
        constraints = [
            models.UniqueConstraint(fields=("weekly_report", "version"), name="unique_report_version")
        ]

    def __str__(self) -> str:
        return f"{self.weekly_report} — versão {self.version}"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="audit_events")
    action = models.CharField(max_length=80)
    entity = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.action} — {self.entity}:{self.entity_id}"

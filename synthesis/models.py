import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from .activity_templates import ACTIVITY_TEMPLATE_CHOICES, LEGACY_TEMPLATE
from .managers import UserManager
from .validators import normalize_image, validate_image_content_type, validate_image_size


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
        constraints = [
            models.UniqueConstraint(Lower("name"), name="area_name_ci_unique"),
            models.CheckConstraint(condition=~Q(name=""), name="area_name_not_empty"),
        ]
        indexes = [
            models.Index(fields=("active", "order"), name="area_active_order_idx"),
        ]

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
    session_version = models.PositiveIntegerField(default=0, editable=False)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    active = models.BooleanField(default=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    objects = UserManager()

    class Meta:
        ordering = ("name", "email")
        constraints = [
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
            models.CheckConstraint(condition=~Q(name=""), name="user_name_not_empty"),
            models.CheckConstraint(condition=Q(role__in=UserRole.values), name="user_role_valid"),
            models.CheckConstraint(
                condition=~Q(role=UserRole.MANAGER) | Q(area__isnull=False),
                name="manager_requires_area",
            ),
        ]
        indexes = [
            models.Index(fields=("role", "active"), name="user_role_active_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.role == UserRole.MANAGER and not self.area_id:
            raise ValidationError({"area": "Um gestor precisa pertencer a uma área."})

    def save(self, *args, **kwargs):
        self.is_active = self.active
        if not self._state.adding:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("active", "role", "password", "session_version")
                .first()
            )
            if previous and (
                previous["active"] != self.active
                or previous["role"] != self.role
                or previous["password"] != self.password
            ):
                self.session_version = previous["session_version"] + 1
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"session_version", "is_active"}
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
            models.CheckConstraint(condition=~Q(label=""), name="cycle_label_not_empty"),
            models.CheckConstraint(
                condition=Q(status__in=CollectionStatus.values),
                name="cycle_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status=CollectionStatus.REOPENED) | ~Q(reopen_reason=""),
                name="reopened_cycle_has_reason",
            ),
            models.UniqueConstraint(
                models.Value(1),
                condition=Q(status__in=(CollectionStatus.OPEN, CollectionStatus.REOPENED)),
                name="one_active_weekly_cycle",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "-starts_at"), name="cycle_status_start_idx"),
        ]

    def clean(self):
        super().clean()
        if self.status in {CollectionStatus.OPEN, CollectionStatus.REOPENED}:
            another_active = (
                type(self).objects.filter(status__in=(CollectionStatus.OPEN, CollectionStatus.REOPENED))
                .exclude(pk=self.pk)
                .exists()
            )
            if another_active:
                raise ValidationError({"status": "Já existe um ciclo ativo. Encerre-o antes de abrir outro."})

    @property
    def accepts_reports(self) -> bool:
        return self.status in {CollectionStatus.OPEN, CollectionStatus.REOPENED}

    def __str__(self) -> str:
        return self.label


class ActivityReport(TimestampedModel):
    template_key = models.CharField(
        max_length=32,
        choices=ACTIVITY_TEMPLATE_CHOICES,
        default=LEGACY_TEMPLATE,
    )
    template_version = models.PositiveSmallIntegerField(default=1, editable=False)
    title = models.CharField(max_length=200)
    date = models.DateField()
    location = models.CharField(max_length=200)
    summary = models.TextField()
    result = models.TextField()
    beneficiaries = models.CharField(max_length=240)
    evidence = models.CharField(max_length=100, blank=True)
    next_step = models.CharField(max_length=140, blank=True)
    internal_notes = models.TextField(blank=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="activity_reports")
    manager = models.ForeignKey(User, on_delete=models.PROTECT, related_name="activity_reports")
    cycle = models.ForeignKey(WeeklyCycle, on_delete=models.PROTECT, related_name="activity_reports")

    class Meta:
        ordering = ("-date", "-created_at")
        constraints = [
            models.CheckConstraint(condition=~Q(title=""), name="activity_title_not_empty"),
            models.CheckConstraint(condition=~Q(location=""), name="activity_location_not_empty"),
            models.CheckConstraint(condition=~Q(summary=""), name="activity_summary_not_empty"),
            models.CheckConstraint(condition=~Q(result=""), name="activity_result_not_empty"),
            models.CheckConstraint(
                condition=~Q(beneficiaries=""),
                name="activity_beneficiaries_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(template_version__gte=1),
                name="activity_template_version_positive",
            ),
        ]
        indexes = [
            models.Index(fields=("cycle", "-date", "-created_at"), name="activity_cycle_date_idx"),
            models.Index(fields=("manager", "cycle"), name="activity_manager_cycle_idx"),
            models.Index(fields=("area", "cycle"), name="activity_area_cycle_idx"),
        ]

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
    is_normalized = models.BooleanField(default=False, editable=False)

    def save(self, *args, **kwargs):
        is_upload = bool(self.image and not self.image._committed)
        if is_upload:
            self.image = normalize_image(self.image.file)
            self.is_normalized = True
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"image", "is_normalized"}
        try:
            return super().save(*args, **kwargs)
        except Exception:
            if is_upload and self.image._committed:
                self.image.storage.delete(self.image.name)
            raise

    class Meta:
        ordering = ("-is_main", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("activity_report",),
                condition=Q(is_main=True),
                name="one_main_photo_per_activity",
            )
        ]
        indexes = [
            models.Index(fields=("activity_report", "-is_main"), name="photo_activity_main_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class ReportStatus(models.TextChoices):
    NOT_STARTED = "nao_iniciado", "Não iniciado"
    SELECTING = "em_selecao", "Em seleção"
    DRAFT = "rascunho", "Rascunho"
    EDITING = "em_edicao", "Em edição"
    PDF_GENERATED = "pdf_gerado", "PDF gerado"


class ExecutiveClassification(models.TextChoices):
    STANDARD = "informativo", "Informativo"
    HIGHLIGHT = "destaque", "Destaque"
    ATTENTION = "atencao", "Ponto de atenção"


class WeeklyReport(TimestampedModel):
    cycle = models.OneToOneField(WeeklyCycle, on_delete=models.PROTECT, related_name="weekly_report")
    status = models.CharField(max_length=20, choices=ReportStatus.choices, default=ReportStatus.DRAFT)
    content_version = models.PositiveIntegerField(default=0, editable=False)
    executive_summary = models.TextField(blank=True)
    selected_activities = models.ManyToManyField(ActivityReport, related_name="weekly_reports", blank=True)

    class Meta:
        ordering = ("-cycle__starts_at",)
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReportStatus.values), name="report_status_valid"),
        ]

    def __str__(self) -> str:
        return f"Relatório — {self.cycle.label}"


class ReportSection(TimestampedModel):
    weekly_report = models.ForeignKey(WeeklyReport, on_delete=models.CASCADE, related_name="sections")
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="report_sections")
    title = models.CharField(max_length=120)
    executive_summary = models.CharField(max_length=180, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("order",)
        constraints = [
            models.UniqueConstraint(fields=("weekly_report", "area"), name="one_section_per_area_report")
        ]
        indexes = [
            models.Index(fields=("weekly_report", "order"), name="section_report_order_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.weekly_report} — {self.title}"


class ReportCard(TimestampedModel):
    section = models.ForeignKey(ReportSection, on_delete=models.CASCADE, related_name="cards")
    activity_report = models.ForeignKey(ActivityReport, on_delete=models.PROTECT, related_name="report_cards")
    editorial_title = models.CharField(max_length=200)
    editorial_summary = models.TextField()
    editorial_result = models.TextField()
    editorial_evidence = models.CharField(max_length=100, blank=True)
    editorial_next_step = models.CharField(max_length=140, blank=True)
    executive_classification = models.CharField(
        max_length=16,
        choices=ExecutiveClassification.choices,
        default=ExecutiveClassification.STANDARD,
    )
    needs_decision = models.BooleanField(default=False)
    decision_request = models.CharField(max_length=180, blank=True)
    next_step_owner = models.CharField(max_length=120, blank=True)
    next_step_due_date = models.DateField(null=True, blank=True)
    selected_photo = models.ForeignKey(ActivityPhoto, on_delete=models.PROTECT, related_name="report_cards")
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name="report_cards")
    original_date = models.DateField()
    original_location = models.CharField(max_length=200)
    original_beneficiaries = models.CharField(max_length=240)
    original_manager_name = models.CharField(max_length=150)
    order = models.PositiveSmallIntegerField(default=0)
    removed = models.BooleanField(default=False)

    class Meta:
        ordering = ("order",)
        constraints = [
            models.UniqueConstraint(fields=("section", "activity_report"), name="one_activity_per_section"),
            models.CheckConstraint(condition=~Q(editorial_title=""), name="card_title_not_empty"),
            models.CheckConstraint(condition=~Q(editorial_summary=""), name="card_summary_not_empty"),
            models.CheckConstraint(condition=~Q(editorial_result=""), name="card_result_not_empty"),
            models.CheckConstraint(
                condition=Q(executive_classification__in=ExecutiveClassification.values),
                name="card_executive_classification_valid",
            ),
        ]
        indexes = [
            models.Index(fields=("section", "removed", "order"), name="card_section_state_order_idx"),
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
            models.UniqueConstraint(fields=("weekly_report", "version"), name="unique_report_version"),
            models.CheckConstraint(condition=Q(version__gte=1), name="report_version_positive"),
        ]
        indexes = [
            models.Index(fields=("weekly_report", "-generated_at"), name="version_report_date_idx"),
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
        constraints = [
            models.CheckConstraint(condition=~Q(action=""), name="audit_action_not_empty"),
            models.CheckConstraint(condition=~Q(entity=""), name="audit_entity_not_empty"),
            models.CheckConstraint(condition=~Q(entity_id=""), name="audit_entity_id_not_empty"),
        ]
        indexes = [
            models.Index(fields=("entity", "entity_id"), name="audit_entity_lookup_idx"),
            models.Index(fields=("actor", "-created_at"), name="audit_actor_date_idx"),
            models.Index(fields=("-created_at",), name="audit_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} — {self.entity}:{self.entity_id}"


class RateWindow(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return self.key

"""Administrative API with explicit resources and the same validation as native forms."""

from datetime import date, datetime
from typing import Any

from django import forms
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, ProtectedError, Q
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404
from ninja import Schema
from ninja.errors import HttpError
from ninja_extra import api_controller, http_delete, http_get, http_post, http_put

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
from .permissions import AdminOnly
from .services import audit


class AreaForm(forms.ModelForm):
    class Meta:
        model = Area
        fields = ("name", "order", "active")
        labels = {"name": "Nome", "order": "Ordem", "active": "Ativa"}


class CycleForm(forms.ModelForm):
    class Meta:
        model = WeeklyCycle
        fields = ("label", "starts_at", "ends_at", "deadline", "status", "reopen_reason")
        labels = {
            "label": "Nome do ciclo",
            "starts_at": "Início",
            "ends_at": "Fim",
            "deadline": "Prazo de envio",
            "status": "Situação",
            "reopen_reason": "Justificativa da reabertura",
        }

    def clean(self):
        data = super().clean()
        start, end = data.get("starts_at"), data.get("ends_at")
        if start and end and end < start:
            self.add_error("ends_at", "O fim precisa ser igual ou posterior ao início.")
        if self.instance.pk and start and end:
            if self.instance.activity_reports.filter(Q(date__lt=start) | Q(date__gt=end)).exists():
                self.add_error("starts_at", "As novas datas precisam abranger os relatos já enviados.")
        reopening = data.get("status") == "reaberta" and (
            self.instance._state.adding or self.instance.status != "reaberta"
        )
        if reopening:
            from django.utils import timezone

            if len(data.get("reopen_reason", "").strip()) < 5:
                self.add_error("reopen_reason", "Informe ao menos 5 caracteres para justificar a reabertura.")
            if data.get("deadline") and data["deadline"] <= timezone.now():
                self.add_error("deadline", "O novo prazo precisa estar no futuro.")
        return data


class UserForm(forms.ModelForm):
    password = forms.CharField(label="Senha", required=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("name", "email", "role", "area", "active", "password")
        labels = {"name": "Nome", "email": "E-mail", "role": "Perfil", "area": "Área", "active": "Ativo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_password = self.instance.password

    def clean(self):
        data = super().clean()
        password = data.get("password")
        if self.instance._state.adding and not password:
            self.add_error("password", "Informe a senha inicial.")
        if password:
            candidate = User(name=data.get("name", ""), email=data.get("email", ""))
            try:
                validate_password(password, candidate)
            except ValidationError as error:
                self.add_error("password", error)
        if data.get("role") == "gestor" and not data.get("area"):
            self.add_error("area", "Um gestor precisa pertencer a uma área.")
        area = data.get("area")
        if area and not area.active and area.pk != self.instance.area_id:
            self.add_error("area", "Selecione uma área ativa.")
        if not self.instance._state.adding and self.instance.activity_reports.exists():
            if data.get("role") != self.instance.role or (area.pk if area else None) != self.instance.area_id:
                self.add_error(None, "Este usuário possui relatos. Preserve o perfil e a área de origem.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if password := self.cleaned_data.get("password"):
            user.set_password(password)
        else:
            user.password = self.original_password
        if commit:
            user.save()
            self.save_m2m()
        return user


class TechnicalUserForm(UserForm):
    class Meta(UserForm.Meta):
        fields = (*UserForm.Meta.fields, "is_staff", "is_superuser", "groups", "user_permissions")
        labels = {
            **UserForm.Meta.labels,
            "is_staff": "Acesso ao Django Admin",
            "is_superuser": "Superusuário",
            "groups": "Grupos",
            "user_permissions": "Permissões individuais",
        }


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ("name", "permissions")
        labels = {"name": "Nome", "permissions": "Permissões"}


# Each field is explicitly selected; passwords and token secrets are never serialized.
RESOURCES = {
    "users": (User, "Usuários", UserForm, ("name", "email", "role", "area", "active"), ("name", "email")),
    "areas": (Area, "Áreas", AreaForm, ("name", "order", "active"), ("name",)),
    "cycles": (
        WeeklyCycle,
        "Ciclos e prazos",
        CycleForm,
        ("label", "starts_at", "ends_at", "deadline", "status", "reopen_reason"),
        ("label",),
    ),
    "groups": (Group, "Grupos", GroupForm, ("name", "permissions"), ("name",)),
    "permissions": (
        Permission,
        "Permissões",
        None,
        ("name", "codename", "content_type"),
        ("name", "codename"),
    ),
    "activities": (
        ActivityReport,
        "Relatos",
        None,
        (
            "template_key",
            "template_version",
            "title",
            "date",
            "location",
            "summary",
            "result",
            "beneficiaries",
            "evidence",
            "next_step",
            "internal_notes",
            "area",
            "manager",
            "cycle",
        ),
        ("title", "manager__name", "area__name"),
    ),
    "photos": (
        ActivityPhoto,
        "Fotos",
        None,
        ("name", "image", "activity_report", "is_main", "alt"),
        ("name", "activity_report__title"),
    ),
    "reports": (
        WeeklyReport,
        "Relatórios semanais",
        None,
        ("cycle", "status", "executive_summary", "selected_activities"),
        ("cycle__label",),
    ),
    "sections": (
        ReportSection,
        "Seções",
        None,
        ("title", "executive_summary", "weekly_report", "area", "order"),
        ("title", "area__name"),
    ),
    "cards": (
        ReportCard,
        "Cards editoriais",
        None,
        (
            "editorial_title",
            "editorial_summary",
            "editorial_result",
            "editorial_evidence",
            "editorial_next_step",
            "executive_classification",
            "needs_decision",
            "decision_request",
            "next_step_owner",
            "next_step_due_date",
            "section",
            "activity_report",
            "selected_photo",
            "area",
            "original_date",
            "order",
            "removed",
        ),
        ("editorial_title",),
    ),
    "versions": (
        ReportVersion,
        "Versões de PDF",
        None,
        ("weekly_report", "version", "generated_at", "generated_by", "pdf"),
        ("weekly_report__cycle__label",),
    ),
    "audit": (
        AuditEvent,
        "Auditoria",
        None,
        ("action", "actor", "entity", "entity_id", "metadata", "created_at"),
        ("action", "entity", "actor__name"),
    ),
}
LABELS = {
    "name": "Nome",
    "email": "E-mail",
    "role": "Perfil",
    "area": "Área",
    "active": "Ativo",
    "order": "Ordem",
    "label": "Ciclo",
    "starts_at": "Início",
    "ends_at": "Fim",
    "deadline": "Prazo",
    "status": "Situação",
    "reopen_reason": "Justificativa",
    "permissions": "Permissões",
    "codename": "Código",
    "content_type": "Tipo de conteúdo",
    "title": "Título",
    "template_key": "Modelo do relato",
    "template_version": "Versão do modelo",
    "date": "Data",
    "location": "Local",
    "summary": "Descrição",
    "result": "Resultado",
    "beneficiaries": "Público beneficiado",
    "evidence": "Evidência",
    "next_step": "Próximo passo",
    "internal_notes": "Informações complementares",
    "manager": "Gestor",
    "cycle": "Ciclo",
    "image": "Imagem",
    "activity_report": "Relato original",
    "is_main": "Foto principal",
    "alt": "Descrição da imagem",
    "selected_activities": "Relatos selecionados",
    "executive_summary": "Síntese executiva",
    "weekly_report": "Relatório",
    "editorial_title": "Título editorial",
    "editorial_summary": "Descrição editorial",
    "editorial_result": "Resultado editorial",
    "editorial_evidence": "Evidência editorial",
    "editorial_next_step": "Próximo passo editorial",
    "executive_classification": "Classificação executiva",
    "needs_decision": "Requer decisão",
    "decision_request": "Decisão solicitada",
    "next_step_owner": "Responsável pelo próximo passo",
    "next_step_due_date": "Prazo do próximo passo",
    "section": "Seção",
    "selected_photo": "Foto selecionada",
    "original_date": "Data original",
    "removed": "Retirado",
    "version": "Versão",
    "generated_at": "Gerado em",
    "generated_by": "Gerado por",
    "pdf": "PDF",
    "action": "Ação",
    "actor": "Responsável",
    "entity": "Registro",
    "entity_id": "Identificador",
    "metadata": "Detalhes",
    "created_at": "Criado em",
    "updated_at": "Atualizado em",
    "date_joined": "Cadastrado em",
    "last_login": "Último acesso",
    "is_staff": "Acesso ao Django Admin",
    "is_superuser": "Superusuário",
    "groups": "Grupos",
    "user_permissions": "Permissões individuais",
}


class AdminInput(Schema):
    values: dict[str, Any]


class AdminRecord(Schema):
    id: str
    label: str
    values: dict[str, Any]
    display: dict[str, Any]
    files: dict[str, str]
    canEdit: bool
    canDelete: bool


class AdminList(Schema):
    items: list[AdminRecord]
    total: int
    page: int
    pageSize: int


class AdminOption(Schema):
    value: str
    label: str


class AdminField(Schema):
    name: str
    label: str
    type: str
    required: bool
    help: str
    maxLength: int | None = None
    options: list[AdminOption] = []


class ResourceOut(Schema):
    key: str
    title: str
    canCreate: bool
    canEdit: bool
    canDelete: bool
    fields: list[AdminField]
    columns: list[AdminOption]
    detailFields: list[AdminOption]
    count: int


def resource_config(key):
    if key not in RESOURCES:
        raise HttpError(404, "Recurso administrativo não encontrado.")
    return RESOURCES[key]


def form_class(key, actor):
    configured = resource_config(key)[2]
    if key == "users" and actor.is_superuser:
        return TechnicalUserForm
    return configured


def can_write(key, actor, instance=None):
    if not form_class(key, actor):
        return False
    if key == "groups" and not actor.is_superuser:
        return False
    if key == "users" and instance and not actor.is_superuser:
        return not (
            instance.is_superuser
            or instance.is_staff
            or instance.groups.exists()
            or instance.user_permissions.exists()
        )
    return True


def queryset(key):
    model, _, _, columns, _ = resource_config(key)
    qs = model.objects.all()
    if not qs.ordered:
        qs = qs.order_by("pk")
    relations, multiple = [], []
    for name in columns:
        field = model._meta.get_field(name)
        if field.many_to_one or field.one_to_one:
            relations.append(name)
        if field.many_to_many:
            multiple.append(name)
    if key == "users":
        return qs.select_related(*relations).prefetch_related(
            "groups",
            Prefetch("user_permissions", queryset=Permission.objects.select_related("content_type")),
        )
    if key == "groups":
        return qs.select_related(*relations).prefetch_related(
            Prefetch("permissions", queryset=Permission.objects.select_related("content_type"))
        )
    return qs.select_related(*relations).prefetch_related(*multiple)


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool, dict, list)) or value is None:
        return value
    return str(value)


def detail_names(key, actor):
    model, _, _, columns, _ = resource_config(key)
    names = list(columns)
    if key == "users":
        names.extend(("date_joined", "last_login"))
        if actor.is_superuser:
            names.extend(("is_staff", "is_superuser", "groups", "user_permissions"))
    for extra in ("created_at", "updated_at"):
        if hasattr(model, extra) and extra not in names:
            names.append(extra)
    return names


def editable_values(key, obj, actor):
    editable = form_class(key, actor)
    if not editable:
        return {}
    fields = [name for name in editable.base_fields if name != "password"]
    values = model_to_dict(obj, fields=fields)
    for name in fields:
        model_field = obj._meta.get_field(name)
        if model_field.many_to_many:
            values[name] = [str(item.pk) for item in getattr(obj, name).all()]
        elif model_field.is_relation:
            values[name] = str(values[name]) if values[name] is not None else ""
        else:
            values[name] = json_value(values[name])
    return values


def display_field(obj, name, request):
    field = obj._meta.get_field(name)
    value = getattr(obj, name)
    if field.many_to_many:
        return [str(item) for item in value.all()], None
    if field.get_internal_type() in {"FileField", "ImageField"}:
        category = "photos" if name == "image" else "versions"
        url = request.build_absolute_uri(f"/api/files/{category}/{obj.pk}") if value else None
        return value.name, url
    if field.is_relation:
        return str(value) if value else None, None
    if field.choices:
        return getattr(obj, f"get_{name}_display")(), None
    return json_value(value), None


def record_data(key, obj, request):
    values = editable_values(key, obj, request.user)
    display, files = {}, {}
    for name in detail_names(key, request.user):
        display[name], url = display_field(obj, name, request)
        if url:
            files[name] = url
    allowed = can_write(key, request.user, obj)
    return {
        "id": str(obj.pk),
        "label": str(obj),
        "values": values,
        "display": display,
        "files": files,
        "canEdit": allowed,
        "canDelete": allowed and not (key == "users" and obj.pk == request.user.pk),
    }


def field_options(field):
    if isinstance(field, (forms.ModelMultipleChoiceField, forms.ModelChoiceField)):
        option_qs = field.queryset
        if option_qs.model is Permission:
            option_qs = option_qs.select_related("content_type")
        return [{"value": str(obj.pk), "label": str(obj)} for obj in option_qs]
    if isinstance(field, forms.ChoiceField):
        return [{"value": str(value), "label": str(label)} for value, label in field.choices if value != ""]
    return []


def field_kind(field):
    mappings = (
        (forms.ModelMultipleChoiceField, "multiple"),
        (forms.ModelChoiceField, "select"),
        (forms.ChoiceField, "select"),
        (forms.BooleanField, "checkbox"),
        (forms.DateTimeField, "datetime-local"),
        (forms.DateField, "date"),
        (forms.IntegerField, "number"),
        (forms.EmailField, "email"),
    )
    for field_type, kind in mappings:
        if isinstance(field, field_type):
            return kind
    if isinstance(field.widget, forms.PasswordInput):
        return "password"
    return "textarea" if isinstance(field.widget, forms.Textarea) else "text"


def field_help(name):
    if name == "password":
        return "Obrigatória ao criar. Deixe em branco ao editar para manter a senha atual."
    if name in {"permissions", "user_permissions", "groups"}:
        return "As permissões técnicas controlam o Django Admin; o perfil controla os fluxos do synthesis."
    return ""


def field_data(name, field):
    return {
        "name": name,
        "label": str(field.label),
        "type": field_kind(field),
        "required": field.required,
        "help": field_help(name),
        "maxLength": getattr(field, "max_length", None),
        "options": field_options(field),
    }


def form_error_message(form):
    return " ".join(
        f"{form.fields[name].label if name in form.fields else 'Registro'}: {message}"
        for name, errors in form.errors.items()
        for message in errors
    )


def protect_current_admin(request, key, instance, form):
    if key != "users" or not instance or instance.pk != request.user.pk:
        return
    data = form.cleaned_data
    if not data.get("active") or data.get("role") != "admin":
        raise HttpError(409, "Você não pode desativar ou remover o próprio perfil de administrador.")
    if request.user.is_superuser and not data.get("is_superuser"):
        raise HttpError(409, "Você não pode remover o próprio acesso de superusuário.")


def validated_form(request, key, payload, instance):
    if not can_write(key, request.user, instance):
        raise HttpError(403, "Você não pode alterar este registro.")
    form = form_class(key, request.user)(data=payload.values, instance=instance)
    unknown = set(payload.values) - set(form.fields)
    if unknown:
        raise HttpError(400, "Campos não permitidos: " + ", ".join(sorted(unknown)))
    if not form.is_valid():
        raise HttpError(400, form_error_message(form))
    protect_current_admin(request, key, instance, form)
    return form


def persist_form(request, key, instance, form):
    try:
        with transaction.atomic():
            previous_cycle = (
                WeeklyCycle.objects.filter(pk=instance.pk).values("status", "deadline").first()
                if key == "cycles" and instance
                else None
            )
            obj = form.save()
            audit(
                request.user,
                f"admin.{key}.{'updated' if instance else 'created'}",
                obj,
                fields=sorted(name for name in form.changed_data if name != "password"),
            )
            if key == "users" and form.cleaned_data.get("password"):
                audit(request.user, "admin.users.password_changed", obj)
            if key == "cycles":
                notifications.cycle_changed(request.user, obj, previous_cycle)
    except IntegrityError as error:
        raise HttpError(409, "Já existe um registro com esses dados.") from error
    return obj


@api_controller("/administration", tags=["administration"], permissions=[AdminOnly()])
class AdministrationController:
    @http_get("/resources", response=list[ResourceOut])
    def resources(self, request):
        output = []
        for key, (model, title, _, columns, _) in RESOURCES.items():
            allowed = can_write(key, request.user)
            configured = form_class(key, request.user)
            fields = (
                [field_data(name, field) for name, field in configured().fields.items()] if configured else []
            )
            names = detail_names(key, request.user)
            output.append(
                {
                    "key": key,
                    "title": title,
                    "canCreate": allowed,
                    "canEdit": allowed,
                    "canDelete": allowed,
                    "fields": fields,
                    "columns": [{"value": name, "label": LABELS[name]} for name in columns[:5]],
                    "detailFields": [{"value": name, "label": LABELS[name]} for name in names],
                    "count": model.objects.count(),
                }
            )
        return output

    @http_get("/{resource}", response=AdminList)
    def list_records(self, request, resource: str, q: str = "", page: int = 1):
        qs = queryset(resource)
        if q.strip():
            filters = Q()
            for field in resource_config(resource)[4]:
                filters |= Q(**{f"{field}__icontains": q.strip()})
            qs = qs.filter(filters)
        if page < 1:
            raise HttpError(400, "Página inválida.")
        total = qs.count()
        items = qs[(page - 1) * 25 : page * 25]
        return {
            "items": [record_data(resource, obj, request) for obj in items],
            "total": total,
            "page": page,
            "pageSize": 25,
        }

    @http_get("/{resource}/{record_id}", response=AdminRecord)
    def get_record(self, request, resource: str, record_id: str):
        return record_data(resource, self._get(resource, record_id), request)

    def _get(self, key, record_id):
        try:
            return get_object_or_404(queryset(key), pk=record_id)
        except (ValidationError, ValueError) as error:
            raise HttpError(404, "Registro não encontrado.") from error

    def _save(self, request, key, payload, instance=None):
        form = validated_form(request, key, payload, instance)
        obj = persist_form(request, key, instance, form)
        return record_data(key, obj, request)

    @http_post("/{resource}", response={201: AdminRecord})
    def create_record(self, request, resource: str, payload: AdminInput):
        from ninja.responses import Status

        return Status(201, self._save(request, resource, payload))

    @http_put("/{resource}/{record_id}", response=AdminRecord)
    def update_record(self, request, resource: str, record_id: str, payload: AdminInput):
        return self._save(request, resource, payload, self._get(resource, record_id))

    @http_delete("/{resource}/{record_id}", response=dict)
    def delete_record(self, request, resource: str, record_id: str):
        obj = self._get(resource, record_id)
        if not can_write(resource, request.user, obj):
            raise HttpError(403, "Você não pode excluir este registro.")
        if resource == "users" and obj.pk == request.user.pk:
            raise HttpError(409, "Você não pode excluir o próprio usuário.")
        if resource == "groups" and obj.user_set.exists():
            raise HttpError(409, "Remova este grupo dos usuários antes de excluí-lo.")
        try:
            with transaction.atomic():
                audit(request.user, f"admin.{resource}.deleted", obj, label=str(obj))
                obj.delete()
        except ProtectedError as error:
            raise HttpError(
                409, "Registro em uso. Preserve o histórico; desative o cadastro quando disponível."
            ) from error
        return {"detail": "Registro excluído."}

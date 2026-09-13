from datetime import date
from uuid import UUID

from django.db import connection
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from ninja import File, Form
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.responses import Status
from ninja_extra import api_controller, http_delete, http_get, http_patch, http_post, permissions

from .models import (
    ActivityReport,
    Area,
    CollectionStatus,
    ReportCard,
    ReportSection,
    ReportStatus,
    ReportVersion,
    User,
    UserRole,
    WeeklyCycle,
    WeeklyReport,
)
from .pagination import Page, paginate
from .permissions import EditorOnly, EditorOrAdmin, ManagerOnly
from .schemas import (
    ActivityCreateIn,
    ActivityReportOut,
    ActivityUpdateIn,
    CollectionOverviewOut,
    CycleDeadlineUpdateIn,
    GenerateDraftIn,
    MessageOut,
    ReopenCollectionIn,
    ReorderCardsIn,
    ReportCardOut,
    ReportCardUpdateIn,
    ReportSectionUpdateIn,
    ReportVersionOut,
    UserOut,
    WeeklyCycleCreateIn,
    WeeklyCycleOut,
    WeeklyReportOut,
    WeeklyReportUpdateIn,
)
from .serializers import activity_data, card_data, cycle_data, report_data, user_data, version_data
from .services import (
    DomainError,
    cancel_report_draft,
    close_cycle,
    create_activity,
    create_cycle,
    generate_draft,
    generate_pdf_version,
    remove_card,
    reopen_cycle,
    reopen_report_selection,
    reorder_cards,
    report_queryset,
    restore_card,
    update_card,
    update_cycle_deadline,
    update_own_activity,
    update_report,
    update_section,
)


def raise_domain_error(error: DomainError):
    raise HttpError(error.status_code, error.message) from error


def activity_queryset():
    return ActivityReport.objects.select_related("area", "manager", "cycle").prefetch_related("photos")


@api_controller("/health", tags=["health"], auth=None, permissions=[permissions.AllowAny])
class HealthController:
    @http_get("", response=MessageOut)
    def health(self):
        return {"detail": "ok"}

    @http_get("/ready", response={200: MessageOut, 503: MessageOut})
    def ready(self):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            return Status(503, {"detail": "indisponível"})
        return Status(200, {"detail": "ok"})


@api_controller("/me", tags=["authentication"])
class AuthenticatedUserController:
    @http_get("", response=UserOut)
    def me(self, request):
        return user_data(request.user)


@api_controller("/areas", tags=["areas"])
class AreaController:
    @http_get("", response=list[str])
    def list_areas(self):
        return list(Area.objects.filter(active=True).values_list("name", flat=True))


@api_controller("/users", tags=["users"])
class UserController:
    @http_get("", response=Page[UserOut])
    def list_users(self, request, page: int = 1, pageSize: int = 25):
        users = User.objects.select_related("area")
        if request.user.role == UserRole.MANAGER:
            users = users.filter(pk=request.user.pk)
        return paginate(users, user_data, page, pageSize)


@api_controller("/cycles", tags=["cycles"])
class CycleController:
    @http_get("", response=Page[WeeklyCycleOut])
    def list_cycles(self, page: int = 1, pageSize: int = 25):
        return paginate(WeeklyCycle.objects.all(), cycle_data, page, pageSize)

    @http_post("", response={201: WeeklyCycleOut}, permissions=[EditorOrAdmin()])
    def create(self, request, payload: WeeklyCycleCreateIn):
        try:
            cycle = create_cycle(
                actor=request.user,
                label=payload.label,
                starts_at=payload.startsAt,
                ends_at=payload.endsAt,
                deadline=payload.deadline,
            )
        except DomainError as error:
            raise_domain_error(error)
        return Status(201, cycle_data(cycle))

    @http_post("/{cycle_id}/close", response=WeeklyCycleOut, permissions=[EditorOrAdmin()])
    def close(self, request, cycle_id: UUID):
        cycle = get_object_or_404(WeeklyCycle, pk=cycle_id)
        try:
            cycle = close_cycle(actor=request.user, cycle=cycle)
        except DomainError as error:
            raise_domain_error(error)
        return cycle_data(cycle)

    @http_patch("/{cycle_id}/deadline", response=WeeklyCycleOut, permissions=[EditorOrAdmin()])
    def deadline(self, request, cycle_id: UUID, payload: CycleDeadlineUpdateIn):
        cycle = get_object_or_404(WeeklyCycle, pk=cycle_id)
        try:
            cycle = update_cycle_deadline(actor=request.user, cycle=cycle, deadline=payload.deadline)
        except DomainError as error:
            raise_domain_error(error)
        return cycle_data(cycle)

    @http_post("/{cycle_id}/reopen", response=WeeklyCycleOut, permissions=[EditorOrAdmin()])
    def reopen(self, request, cycle_id: UUID, payload: ReopenCollectionIn):
        cycle = get_object_or_404(WeeklyCycle, pk=cycle_id)
        try:
            cycle = reopen_cycle(
                actor=request.user,
                cycle=cycle,
                reason=payload.reason,
                new_deadline=payload.newDeadline,
            )
        except DomainError as error:
            raise_domain_error(error)
        return cycle_data(cycle)


@api_controller("/activity-reports", tags=["activity reports"])
class ActivityReportController:
    @http_get("", response=Page[ActivityReportOut])
    def list_reports(
        self,
        request,
        area: str | None = None,
        managerId: UUID | None = None,
        cycleId: UUID | None = None,
        page: int = 1,
        pageSize: int = 25,
        q: str = "",
        startDate: date | None = None,
        endDate: date | None = None,
    ):
        queryset = activity_queryset()
        if request.user.role == UserRole.MANAGER:
            queryset = queryset.filter(manager=request.user)
        if area:
            queryset = queryset.filter(area__name=area)
        if managerId:
            queryset = queryset.filter(manager_id=managerId)
        if cycleId:
            queryset = queryset.filter(cycle_id=cycleId)
        if len(q) > 200:
            raise HttpError(400, "A busca deve ter no máximo 200 caracteres.")
        if q.strip():
            queryset = queryset.filter(
                Q(title__icontains=q.strip())
                | Q(location__icontains=q.strip())
                | Q(summary__icontains=q.strip())
                | Q(result__icontains=q.strip())
            )
        if startDate:
            queryset = queryset.filter(date__gte=startDate)
        if endDate:
            queryset = queryset.filter(date__lte=endDate)
        return paginate(queryset, lambda item: activity_data(item, request), page, pageSize)

    @http_get("/{report_id}", response=ActivityReportOut)
    def get_report(self, request, report_id: UUID):
        queryset = activity_queryset()
        if request.user.role == UserRole.MANAGER:
            queryset = queryset.filter(manager=request.user)
        return activity_data(get_object_or_404(queryset, pk=report_id), request)

    @http_post("", response={201: ActivityReportOut}, permissions=[ManagerOnly()])
    def create_report(
        self,
        request,
        payload: Form[ActivityCreateIn],
        photos: File[list[UploadedFile]],
    ):
        try:
            activity = create_activity(
                actor=request.user,
                data=payload.model_dump(),
                photos=photos,
            )
        except DomainError as error:
            raise_domain_error(error)
        activity = activity_queryset().get(pk=activity.pk)
        return Status(201, activity_data(activity, request))

    @http_patch("/{report_id}", response=ActivityReportOut, permissions=[ManagerOnly()])
    def update_report(self, request, report_id: UUID, payload: ActivityUpdateIn):
        report = get_object_or_404(activity_queryset(), pk=report_id)
        try:
            report = update_own_activity(
                actor=request.user,
                report=report,
                changes=payload.model_dump(exclude_none=True),
            )
        except DomainError as error:
            raise_domain_error(error)
        return activity_data(report, request)


@api_controller("/collection", tags=["collection"])
class CollectionController:
    def _current_cycle(self):
        cycle = (
            WeeklyCycle.objects.filter(status__in=(CollectionStatus.OPEN, CollectionStatus.REOPENED))
            .order_by("-starts_at")
            .first()
        )
        return cycle or WeeklyCycle.objects.order_by("-starts_at").first()

    @http_get("/overview", response=CollectionOverviewOut, permissions=[EditorOrAdmin()])
    def overview(self):
        cycle = self._current_cycle()
        if cycle is None:
            raise HttpError(404, "Nenhum ciclo cadastrado.")
        managers = list(User.objects.filter(role=UserRole.MANAGER, active=True).select_related("area"))
        submitted_ids = set(
            ActivityReport.objects.filter(cycle=cycle).values_list("manager_id", flat=True).distinct()
        )
        report = getattr(cycle, "weekly_report", None)
        return {
            "cycle": cycle_data(cycle),
            "submittedManagers": [user_data(user) for user in managers if user.id in submitted_ids],
            "pendingManagers": [user_data(user) for user in managers if user.id not in submitted_ids],
            "totalReports": cycle.activity_reports.count(),
            "reportStatus": report.status if report else ReportStatus.NOT_STARTED,
        }

    @http_get("/pending-managers", response=list[UserOut], permissions=[EditorOrAdmin()])
    def pending_managers(self):
        cycle = self._current_cycle()
        if cycle is None:
            return []
        users = (
            User.objects.filter(role=UserRole.MANAGER, active=True)
            .select_related("area")
            .annotate(
                reports_in_cycle=Count(
                    "activity_reports",
                    filter=Q(activity_reports__cycle=cycle),
                )
            )
            .filter(reports_in_cycle=0)
        )
        return [user_data(user) for user in users]


@api_controller("/weekly-reports", tags=["weekly reports"], permissions=[EditorOnly()])
class WeeklyReportController:
    @http_get("", response=Page[WeeklyReportOut])
    def list_reports(self, request, page: int = 1, pageSize: int = 25, cycleId: UUID | None = None):
        reports = report_queryset()
        if cycleId:
            reports = reports.filter(cycle_id=cycleId)
        return paginate(reports, lambda item: report_data(item, request, summary=True), page, pageSize)

    @http_post("/draft", response={201: WeeklyReportOut})
    def create_draft(self, request, payload: GenerateDraftIn):
        try:
            report = generate_draft(
                actor=request.user,
                cycle_id=payload.cycleId,
                activity_ids=payload.activityIds,
            )
        except DomainError as error:
            raise_domain_error(error)
        return Status(201, report_data(report, request))

    @http_get("/{report_id}", response=WeeklyReportOut)
    def get_report(self, request, report_id: UUID):
        return report_data(get_object_or_404(report_queryset(), pk=report_id), request)

    @http_patch("/{report_id}", response=WeeklyReportOut)
    def patch_report(self, request, report_id: UUID, payload: WeeklyReportUpdateIn):
        report = get_object_or_404(WeeklyReport, pk=report_id)
        try:
            report = update_report(
                actor=request.user,
                report=report,
                executive_summary=payload.executiveSummary,
            )
        except DomainError as error:
            raise_domain_error(error)
        return report_data(report, request)

    @http_post("/{report_id}/selection/reopen", response=WeeklyReportOut)
    def reopen_selection(self, request, report_id: UUID):
        report = get_object_or_404(WeeklyReport, pk=report_id)
        try:
            report = reopen_report_selection(actor=request.user, report=report)
        except DomainError as error:
            raise_domain_error(error)
        return report_data(report, request)

    @http_delete("/{report_id}", response=MessageOut)
    def cancel_draft(self, request, report_id: UUID):
        report = get_object_or_404(WeeklyReport, pk=report_id)
        try:
            cancel_report_draft(actor=request.user, report=report)
        except DomainError as error:
            raise_domain_error(error)
        return {"detail": "Rascunho cancelado."}

    @http_patch("/{report_id}/cards/{card_id}", response=ReportCardOut)
    def patch_card(self, request, report_id: UUID, card_id: UUID, payload: ReportCardUpdateIn):
        card = get_object_or_404(
            ReportCard.objects.select_related("activity_report", "section__weekly_report", "area"),
            pk=card_id,
            section__weekly_report_id=report_id,
        )
        try:
            card = update_card(
                actor=request.user,
                card=card,
                changes=payload.model_dump(exclude_unset=True),
            )
        except DomainError as error:
            raise_domain_error(error)
        return card_data(card)

    @http_patch("/{report_id}/sections/{section_id}", response=WeeklyReportOut)
    def patch_section(
        self,
        request,
        report_id: UUID,
        section_id: UUID,
        payload: ReportSectionUpdateIn,
    ):
        section = get_object_or_404(
            ReportSection.objects.select_related("weekly_report"),
            pk=section_id,
            weekly_report_id=report_id,
        )
        try:
            report = update_section(
                actor=request.user,
                section=section,
                executive_summary=payload.executiveSummary,
            )
        except DomainError as error:
            raise_domain_error(error)
        return report_data(report, request)

    @http_post("/{report_id}/sections/{section_id}/reorder", response=WeeklyReportOut)
    def reorder(self, request, report_id: UUID, section_id: UUID, payload: ReorderCardsIn):
        section = get_object_or_404(
            ReportSection.objects.select_related("weekly_report").prefetch_related("cards"),
            pk=section_id,
            weekly_report_id=report_id,
        )
        try:
            report = reorder_cards(actor=request.user, section=section, card_ids=payload.cardIds)
        except DomainError as error:
            raise_domain_error(error)
        return report_data(report, request)

    @http_delete("/{report_id}/cards/{card_id}", response=WeeklyReportOut)
    def delete_card(self, request, report_id: UUID, card_id: UUID):
        card = get_object_or_404(
            ReportCard.objects.select_related("section__weekly_report"),
            pk=card_id,
            section__weekly_report_id=report_id,
        )
        try:
            report = remove_card(actor=request.user, card=card)
        except DomainError as error:
            raise_domain_error(error)
        return report_data(report, request)

    @http_post("/{report_id}/cards/{card_id}/restore", response=WeeklyReportOut)
    def restore_removed_card(self, request, report_id: UUID, card_id: UUID):
        card = get_object_or_404(
            ReportCard.objects.select_related("section__weekly_report"),
            pk=card_id,
            section__weekly_report_id=report_id,
        )
        try:
            report = restore_card(actor=request.user, card=card)
        except DomainError as error:
            raise_domain_error(error)
        return report_data(report, request)

    @http_get("/{report_id}/versions", response=Page[ReportVersionOut])
    def list_versions(self, request, report_id: UUID, page: int = 1, pageSize: int = 25):
        versions = ReportVersion.objects.filter(weekly_report_id=report_id).select_related("generated_by")
        return paginate(versions, lambda item: version_data(item, request), page, pageSize)

    @http_post("/{report_id}/versions", response={201: ReportVersionOut})
    def generate_version(self, request, report_id: UUID):
        try:
            version = generate_pdf_version(actor=request.user, report_id=report_id)
        except DomainError as error:
            raise_domain_error(error)
        return Status(201, version_data(version, request))

    @http_get("/versions/{version_id}/url", response=str)
    def version_url(self, request, version_id: UUID):
        version = get_object_or_404(ReportVersion, pk=version_id)
        return request.build_absolute_uri(f"/api/files/versions/{version.id}")

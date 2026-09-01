from uuid import UUID

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
)
from .permissions import AdminOnly, EditorOnly, EditorOrAdmin, ManagerOnly
from .schemas import (
    ActivityCreateIn,
    ActivityReportOut,
    ActivityUpdateIn,
    CollectionOverviewOut,
    GenerateDraftIn,
    MessageOut,
    ReopenCollectionIn,
    ReorderCardsIn,
    ReportCardOut,
    ReportCardUpdateIn,
    ReportVersionOut,
    UserOut,
    WeeklyCycleOut,
    WeeklyReportOut,
)
from .serializers import activity_data, card_data, cycle_data, report_data, user_data, version_data
from .services import (
    DomainError,
    create_activity,
    generate_draft,
    generate_pdf_version,
    remove_card,
    reopen_cycle,
    reorder_cards,
    report_queryset,
    update_card,
    update_own_activity,
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
    @http_get("", response=list[UserOut])
    def list_users(self):
        return [user_data(user) for user in User.objects.select_related("area").all()]


@api_controller("/cycles", tags=["cycles"])
class CycleController:
    @http_get("", response=list[WeeklyCycleOut])
    def list_cycles(self):
        return [cycle_data(cycle) for cycle in WeeklyCycle.objects.all()]

    @http_post("/{cycle_id}/reopen", response=WeeklyCycleOut, permissions=[AdminOnly()])
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
    @http_get("", response=list[ActivityReportOut])
    def list_reports(
        self,
        request,
        area: str | None = None,
        managerId: UUID | None = None,
        cycleId: UUID | None = None,
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
        return [activity_data(activity, request) for activity in queryset]

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
    @http_get("", response=list[WeeklyReportOut])
    def list_reports(self, request):
        return [report_data(report, request) for report in report_queryset()]

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
                changes=payload.model_dump(exclude_none=True),
            )
        except DomainError as error:
            raise_domain_error(error)
        return card_data(card)

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

    @http_get("/{report_id}/versions", response=list[ReportVersionOut])
    def list_versions(self, request, report_id: UUID):
        versions = ReportVersion.objects.filter(weekly_report_id=report_id).select_related("generated_by")
        return [version_data(version, request) for version in versions]

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
        return request.build_absolute_uri(version.pdf.url)

from django.http import HttpRequest

from .models import ActivityReport, ReportCard, ReportSection, ReportVersion, User, WeeklyCycle, WeeklyReport


def user_data(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "area": user.area.name if user.area_id else None,
        "role": user.role,
        "active": user.active,
    }


def cycle_data(cycle: WeeklyCycle) -> dict:
    return {
        "id": cycle.id,
        "label": cycle.label,
        "startsAt": cycle.starts_at,
        "endsAt": cycle.ends_at,
        "deadline": cycle.deadline,
        "status": cycle.status,
    }


def activity_data(activity: ActivityReport, request: HttpRequest) -> dict:
    return {
        "id": activity.id,
        "title": activity.title,
        "date": activity.date,
        "location": activity.location,
        "summary": activity.summary,
        "result": activity.result,
        "beneficiaries": activity.beneficiaries,
        "area": activity.area.name,
        "managerId": activity.manager_id,
        "cycleId": activity.cycle_id,
        "photos": [
            {
                "id": photo.id,
                "url": request.build_absolute_uri(photo.image.url),
                "name": photo.name,
                "isMain": photo.is_main,
                "alt": photo.alt,
            }
            for photo in activity.photos.all()
        ],
        "createdAt": activity.created_at,
        "updatedAt": activity.updated_at,
    }


def card_data(card: ReportCard) -> dict:
    return {
        "id": card.id,
        "activityReportId": card.activity_report_id,
        "editorialTitle": card.editorial_title,
        "editorialSummary": card.editorial_summary,
        "editorialResult": card.editorial_result,
        "selectedPhotoId": card.selected_photo_id,
        "area": card.area.name,
        "originalDate": card.original_date,
        "order": card.order,
        "removed": card.removed,
    }


def section_data(section: ReportSection) -> dict:
    return {
        "id": section.id,
        "area": section.area.name,
        "title": section.title,
        "order": section.order,
        "cards": [card_data(card) for card in section.cards.all()],
    }


def version_data(version: ReportVersion, request: HttpRequest) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "generatedAt": version.generated_at,
        "generatedBy": version.generated_by_id,
        "pdfUrl": request.build_absolute_uri(version.pdf.url),
    }


def report_data(report: WeeklyReport, request: HttpRequest) -> dict:
    return {
        "id": report.id,
        "cycleId": report.cycle_id,
        "status": report.status,
        "selectedActivityIds": list(report.selected_activities.values_list("id", flat=True)),
        "sections": [section_data(section) for section in report.sections.all()],
        "versions": [version_data(version, request) for version in report.versions.all()],
        "updatedAt": report.updated_at,
    }

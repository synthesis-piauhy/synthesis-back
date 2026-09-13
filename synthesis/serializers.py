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
        "templateKey": activity.template_key,
        "templateVersion": activity.template_version,
        "title": activity.title,
        "date": activity.date,
        "location": activity.location,
        "summary": activity.summary,
        "result": activity.result,
        "beneficiaries": activity.beneficiaries,
        "evidence": activity.evidence,
        "nextStep": activity.next_step,
        "internalNotes": activity.internal_notes,
        "area": activity.area.name,
        "managerId": activity.manager_id,
        "cycleId": activity.cycle_id,
        "photos": [
            {
                "id": photo.id,
                "url": request.build_absolute_uri(f"/api/files/photos/{photo.id}"),
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
        "editorialEvidence": card.editorial_evidence,
        "editorialNextStep": card.editorial_next_step,
        "executiveClassification": card.executive_classification,
        "needsDecision": card.needs_decision,
        "decisionRequest": card.decision_request,
        "nextStepOwner": card.next_step_owner,
        "nextStepDueDate": card.next_step_due_date,
        "selectedPhotoId": card.selected_photo_id,
        "area": card.area.name,
        "originalDate": card.original_date,
        "originalLocation": card.original_location,
        "originalBeneficiaries": card.original_beneficiaries,
        "originalManagerName": card.original_manager_name,
        "order": card.order,
        "removed": card.removed,
    }


def section_data(section: ReportSection, include_cards=True) -> dict:
    return {
        "id": section.id,
        "area": section.area.name,
        "title": section.title,
        "executiveSummary": section.executive_summary,
        "order": section.order,
        "cards": [card_data(card) for card in section.cards.all()] if include_cards else [],
    }


def version_data(version: ReportVersion, request: HttpRequest) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "generatedAt": version.generated_at,
        "generatedBy": version.generated_by_id,
        "pdfUrl": request.build_absolute_uri(f"/api/files/versions/{version.id}"),
    }


def report_data(report: WeeklyReport, request: HttpRequest, summary=False) -> dict:
    sections = [section_data(section, include_cards=not summary) for section in report.sections.all()]
    versions = list(report.versions.all())
    return {
        "id": report.id,
        "cycleId": report.cycle_id,
        "status": report.status,
        "executiveSummary": report.executive_summary,
        "selectedActivityIds": [item.pk for item in report.selected_activities.all()],
        "sections": sections,
        "versions": [version_data(version, request) for version in (versions[-1:] if summary else versions)],
        "updatedAt": report.updated_at,
    }

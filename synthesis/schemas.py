from datetime import date as Date
from datetime import datetime as DateTime
from uuid import UUID

from ninja import Schema
from pydantic import Field

from .activity_templates import PUBLISHABLE_LIMITS


class MessageOut(Schema):
    detail: str


class UserOut(Schema):
    id: UUID
    name: str
    email: str
    area: str | None
    role: str
    active: bool


class WeeklyCycleOut(Schema):
    id: UUID
    label: str
    startsAt: Date
    endsAt: Date
    deadline: DateTime
    status: str


class WeeklyCycleCreateIn(Schema):
    label: str = Field(min_length=3, max_length=120)
    startsAt: Date
    endsAt: Date
    deadline: DateTime


class CycleDeadlineUpdateIn(Schema):
    deadline: DateTime


class ActivityPhotoOut(Schema):
    id: UUID
    url: str
    name: str
    isMain: bool
    alt: str


class ActivityReportOut(Schema):
    id: UUID
    templateKey: str
    templateVersion: int
    title: str
    date: Date
    location: str
    summary: str
    result: str
    beneficiaries: str
    evidence: str
    nextStep: str
    internalNotes: str
    area: str
    managerId: UUID
    cycleId: UUID
    photos: list[ActivityPhotoOut]
    createdAt: DateTime
    updatedAt: DateTime


class ActivityCreateIn(Schema):
    templateKey: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=3, max_length=PUBLISHABLE_LIMITS["title"])
    date: Date
    location: str = Field(min_length=2, max_length=200)
    summary: str = Field(min_length=10, max_length=PUBLISHABLE_LIMITS["summary"])
    result: str = Field(min_length=10, max_length=PUBLISHABLE_LIMITS["result"])
    beneficiaries: str = Field(min_length=2, max_length=PUBLISHABLE_LIMITS["beneficiaries"])
    evidence: str = Field(default="", max_length=PUBLISHABLE_LIMITS["evidence"])
    nextStep: str = Field(default="", max_length=PUBLISHABLE_LIMITS["nextStep"])
    internalNotes: str = Field(default="", max_length=PUBLISHABLE_LIMITS["internalNotes"])
    cycleId: UUID


class ActivityUpdateIn(Schema):
    title: str | None = Field(default=None, min_length=3, max_length=PUBLISHABLE_LIMITS["title"])
    date: Date | None = None
    location: str | None = Field(default=None, min_length=2, max_length=200)
    summary: str | None = Field(default=None, min_length=10, max_length=PUBLISHABLE_LIMITS["summary"])
    result: str | None = Field(default=None, min_length=10, max_length=PUBLISHABLE_LIMITS["result"])
    beneficiaries: str | None = Field(
        default=None,
        min_length=2,
        max_length=PUBLISHABLE_LIMITS["beneficiaries"],
    )
    evidence: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["evidence"])
    nextStep: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["nextStep"])
    internalNotes: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["internalNotes"])


class ReportCardOut(Schema):
    id: UUID
    activityReportId: UUID
    editorialTitle: str
    editorialSummary: str
    editorialResult: str
    editorialEvidence: str
    editorialNextStep: str
    executiveClassification: str
    needsDecision: bool
    decisionRequest: str
    nextStepOwner: str
    nextStepDueDate: Date | None
    selectedPhotoId: UUID
    area: str
    originalDate: Date
    originalLocation: str
    originalBeneficiaries: str
    originalManagerName: str
    order: int
    removed: bool


class ReportSectionOut(Schema):
    id: UUID
    area: str
    title: str
    executiveSummary: str
    order: int
    cards: list[ReportCardOut]


class ReportVersionOut(Schema):
    id: UUID
    version: int
    generatedAt: DateTime
    generatedBy: UUID
    pdfUrl: str


class WeeklyReportOut(Schema):
    id: UUID
    cycleId: UUID
    status: str
    executiveSummary: str
    selectedActivityIds: list[UUID]
    sections: list[ReportSectionOut]
    versions: list[ReportVersionOut]
    updatedAt: DateTime


class CollectionOverviewOut(Schema):
    cycle: WeeklyCycleOut
    submittedManagers: list[UserOut]
    pendingManagers: list[UserOut]
    totalReports: int
    reportStatus: str


class ReopenCollectionIn(Schema):
    reason: str = Field(min_length=5, max_length=2000)
    newDeadline: DateTime


class GenerateDraftIn(Schema):
    cycleId: UUID
    activityIds: list[UUID] = Field(min_length=1, max_length=500)


class ReportCardUpdateIn(Schema):
    editorialTitle: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["title"])
    editorialSummary: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["summary"])
    editorialResult: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["result"])
    editorialEvidence: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["evidence"])
    editorialNextStep: str | None = Field(default=None, max_length=PUBLISHABLE_LIMITS["nextStep"])
    executiveClassification: str | None = Field(default=None, max_length=16)
    needsDecision: bool | None = None
    decisionRequest: str | None = Field(default=None, max_length=180)
    nextStepOwner: str | None = Field(default=None, max_length=120)
    nextStepDueDate: Date | None = None
    selectedPhotoId: UUID | None = None


class WeeklyReportUpdateIn(Schema):
    executiveSummary: str = Field(max_length=400)


class ReportSectionUpdateIn(Schema):
    executiveSummary: str = Field(max_length=180)


class ReorderCardsIn(Schema):
    cardIds: list[UUID] = Field(min_length=1, max_length=500)

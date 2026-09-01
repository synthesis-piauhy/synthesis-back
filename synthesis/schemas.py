from datetime import date as Date
from datetime import datetime as DateTime
from uuid import UUID

from ninja import Schema


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


class ActivityPhotoOut(Schema):
    id: UUID
    url: str
    name: str
    isMain: bool
    alt: str


class ActivityReportOut(Schema):
    id: UUID
    title: str
    date: Date
    location: str
    summary: str
    result: str
    beneficiaries: str
    area: str
    managerId: UUID
    cycleId: UUID
    photos: list[ActivityPhotoOut]
    createdAt: DateTime
    updatedAt: DateTime


class ActivityCreateIn(Schema):
    title: str
    date: Date
    location: str
    summary: str
    result: str
    beneficiaries: str
    cycleId: UUID


class ActivityUpdateIn(Schema):
    title: str | None = None
    date: Date | None = None
    location: str | None = None
    summary: str | None = None
    result: str | None = None
    beneficiaries: str | None = None


class ReportCardOut(Schema):
    id: UUID
    activityReportId: UUID
    editorialTitle: str
    editorialSummary: str
    editorialResult: str
    selectedPhotoId: UUID
    area: str
    originalDate: Date
    order: int
    removed: bool


class ReportSectionOut(Schema):
    id: UUID
    area: str
    title: str
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
    reason: str
    newDeadline: DateTime


class GenerateDraftIn(Schema):
    cycleId: UUID
    activityIds: list[UUID]


class ReportCardUpdateIn(Schema):
    editorialTitle: str | None = None
    editorialSummary: str | None = None
    editorialResult: str | None = None
    selectedPhotoId: UUID | None = None


class ReorderCardsIn(Schema):
    cardIds: list[UUID]

from datetime import date as Date
from datetime import datetime as DateTime
from uuid import UUID

from ninja import Schema
from pydantic import Field


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
    title: str = Field(min_length=3, max_length=200)
    date: Date
    location: str = Field(min_length=2, max_length=200)
    summary: str = Field(min_length=10, max_length=10000)
    result: str = Field(min_length=10, max_length=10000)
    beneficiaries: str = Field(min_length=2, max_length=240)
    cycleId: UUID


class ActivityUpdateIn(Schema):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    date: Date | None = None
    location: str | None = Field(default=None, min_length=2, max_length=200)
    summary: str | None = Field(default=None, min_length=10, max_length=10000)
    result: str | None = Field(default=None, min_length=10, max_length=10000)
    beneficiaries: str | None = Field(default=None, min_length=2, max_length=240)


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
    reason: str = Field(min_length=5, max_length=2000)
    newDeadline: DateTime


class GenerateDraftIn(Schema):
    cycleId: UUID
    activityIds: list[UUID] = Field(min_length=1, max_length=500)


class ReportCardUpdateIn(Schema):
    editorialTitle: str | None = Field(default=None, max_length=200)
    editorialSummary: str | None = Field(default=None, max_length=10000)
    editorialResult: str | None = Field(default=None, max_length=10000)
    selectedPhotoId: UUID | None = None


class ReorderCardsIn(Schema):
    cardIds: list[UUID] = Field(min_length=1, max_length=500)

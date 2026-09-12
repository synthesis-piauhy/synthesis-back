from ninja_extra import NinjaExtraAPI

from .administration import AdministrationController
from .authentication import BrowserSessionAuth
from .controllers import (
    ActivityReportController,
    AreaController,
    AuthenticatedUserController,
    CollectionController,
    CycleController,
    HealthController,
    UserController,
    WeeklyReportController,
)
from .files import FileController

api = NinjaExtraAPI(
    title="synthesis API",
    version="0.1.0",
    description="API editorial e de coleta semanal da plataforma synthesis.",
    auth=BrowserSessionAuth(),
)
api.register_controllers(
    FileController,
    HealthController,
    AuthenticatedUserController,
    AreaController,
    UserController,
    CycleController,
    ActivityReportController,
    CollectionController,
    WeeklyReportController,
    AdministrationController,
)

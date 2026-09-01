from ninja_extra import NinjaExtraAPI
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.controller import NinjaJWTDefaultController

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

api = NinjaExtraAPI(
    title="synthesis API",
    version="0.1.0",
    description="API editorial e de coleta semanal da plataforma synthesis.",
    auth=JWTAuth(),
)
api.register_controllers(
    NinjaJWTDefaultController,
    HealthController,
    AuthenticatedUserController,
    AreaController,
    UserController,
    CycleController,
    ActivityReportController,
    CollectionController,
    WeeklyReportController,
)

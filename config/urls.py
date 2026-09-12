from django.contrib import admin
from django.urls import path

from synthesis.api import api
from synthesis.authentication import csrf_token, login_view, logout_all_view, logout_view, verify_session

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/csrf", csrf_token),
    path("api/token/pair", login_view),
    path("api/token/refresh", verify_session),
    path("api/token/verify", verify_session),
    path("api/token/logout", logout_view),
    path("api/token/logout-all", logout_all_view),
    path("api/", api.urls),
]

"""URL configuration for acelera_agro project."""

from django.contrib import admin
from django.urls import path

from acelera_agro.api import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]

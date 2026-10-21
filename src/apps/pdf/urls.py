"""PDF URL routing, mounted under ``/api/v1/``."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"pdf/jobs", views.PDFJobViewSet, basename="pdf-job")

urlpatterns = [
    path("pdf/render/", views.PDFRenderView.as_view(), name="pdf-render"),
    *router.urls,
]

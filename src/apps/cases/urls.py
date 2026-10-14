"""Case filing URL routing (spec 0021)."""

from django.urls import path

from . import views

urlpatterns = [
    path("case-types/", views.CaseTypeListView.as_view(), name="case-type-list"),
    path(
        "case-types/<str:case_type>/",
        views.CaseTypeDetailView.as_view(),
        name="case-type-detail",
    ),
    path("cases/", views.CaseListView.as_view(), name="case-list"),
    # Case numbers contain slashes (CC/123/2024).
    path(
        "cases/by-number/<path:case_number>/",
        views.CaseByNumberView.as_view(),
        name="case-by-number",
    ),
    path(
        "cases/<uuid:case_id>/documents/",
        views.CaseDocumentListView.as_view(),
        name="case-document-list",
    ),
    path(
        "cases/<uuid:case_id>/documents/<uuid:case_document_id>/",
        views.CaseDocumentDetailView.as_view(),
        name="case-document-detail",
    ),
    path("cases/<uuid:case_id>/details/", views.CaseDetailsView.as_view(), name="case-details"),
    path(
        "cases/<uuid:case_id>/details/<str:section>/",
        views.CaseDetailsSectionView.as_view(),
        name="case-details-section",
    ),
    path(
        "cases/<uuid:case_id>/evidence/",
        views.CaseEvidenceListView.as_view(),
        name="case-evidence-list",
    ),
    path(
        "cases/<uuid:case_id>/evidence/<uuid:case_evidence_id>/",
        views.CaseEvidenceDetailView.as_view(),
        name="case-evidence-detail",
    ),
]

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
    path("cases/<uuid:case_id>/", views.CasePreviewView.as_view(), name="case-detail"),
    path("cases/<uuid:case_id>/validate/", views.CaseValidateView.as_view(), name="case-validate"),
    path(
        "cases/<uuid:case_id>/submit-for-signing/",
        views.SubmitForSigningView.as_view(),
        name="case-submit-for-signing",
    ),
    path(
        "cases/<uuid:case_id>/submit-for-payment/",
        views.SubmitForPaymentView.as_view(),
        name="case-submit-for-payment",
    ),
    path(
        "cases/<uuid:case_id>/submit-for-scrutiny/",
        views.SubmitForScrutinyView.as_view(),
        name="case-submit-for-scrutiny",
    ),
    path(
        "cases/<uuid:case_id>/documents/",
        views.CaseDocumentListView.as_view(),
        name="case-document-list",
    ),
    path(
        "cases/<uuid:case_id>/affidavit/", views.CaseAffidavitView.as_view(), name="case-affidavit"
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
        "cases/<uuid:case_id>/complainants/",
        views.ComplainantCreateView.as_view(),
        name="case-complainant-list",
    ),
    path(
        "cases/<uuid:case_id>/accused/",
        views.AccusedCreateView.as_view(),
        name="case-accused-list",
    ),
    path(
        "cases/<uuid:case_id>/witnesses/",
        views.WitnessCreateView.as_view(),
        name="case-witness-list",
    ),
    path(
        "cases/<uuid:case_id>/participants/",
        views.CaseParticipantListView.as_view(),
        name="case-participant-list",
    ),
    path(
        "cases/<uuid:case_id>/participants/<uuid:case_participant_id>/sign/",
        views.ParticipantSignView.as_view(),
        name="case-participant-sign",
    ),
    path(
        "cases/<uuid:case_id>/advocates/",
        views.AdvocateCreateView.as_view(),
        name="case-advocate-list",
    ),
    path(
        "cases/<uuid:case_id>/representations/",
        views.RepresentationListView.as_view(),
        name="case-representation-list",
    ),
    path(
        "cases/<uuid:case_id>/poa-holders/",
        views.PoaHolderCreateView.as_view(),
        name="case-poa-holder-list",
    ),
    path(
        "cases/<uuid:case_id>/poa-mandates/",
        views.PoaMandateListView.as_view(),
        name="case-poa-mandate-list",
    ),
    # Items are changed by their own id: it is unique across cases, and the
    # owning case is found through it.
    path(
        "case-participants/<uuid:case_participant_id>/",
        views.CaseParticipantDetailView.as_view(),
        name="case-participant-detail",
    ),
    path(
        "case-documents/<uuid:case_document_id>/",
        views.CaseDocumentDetailView.as_view(),
        name="case-document-detail",
    ),
    path(
        "case-evidence/<uuid:case_evidence_id>/",
        views.CaseEvidenceDetailView.as_view(),
        name="case-evidence-detail",
    ),
    path(
        "poa-mandates/<uuid:poa_mandate_id>/",
        views.PoaMandateDetailView.as_view(),
        name="poa-mandate-detail",
    ),
    path(
        "representations/<uuid:representation_id>/",
        views.RepresentationDetailView.as_view(),
        name="representation-detail",
    ),
]

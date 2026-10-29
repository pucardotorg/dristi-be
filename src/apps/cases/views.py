"""Case filing API views (spec 0021 §2–8).

Ids in POST/PUT paths may be a case id or a draft session id; the first save
on a draft creates the case (see ``services.get_or_create_case``). Other case
routes take a case id; a document, evidence item, participant, mandate or
representation is changed by its own id (``/case-documents/{id}``,
``/case-evidence/{id}``, ``/case-participants/{id}``, ``/poa-mandates/{id}``,
``/representations/{id}``). Callers only ever reach their own cases.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api import errors as api_errors
from apps.api.schema import error_responses

from . import errors
from .models import (
    ADDRESS_REQUIRED_MESSAGE,
    EVIDENCE_ORDERING,
    JOINABLE_STATUSES,
    PARTICIPANT_ORDERING,
    POA_MANDATE_ORDERING,
    REPRESENTATION_ORDERING,
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ParticipantRole,
    PoaMandate,
    Representation,
)
from .serializers import (
    AdvocateCreatedSerializer,
    AdvocateCreateSerializer,
    CaseDocumentSerializer,
    CaseDocumentUploadSerializer,
    CaseEvidenceSerializer,
    CaseParticipantSerializer,
    CasePreviewSerializer,
    CaseSerializer,
    CaseTypeDescriptionSerializer,
    CaseValidationSerializer,
    DetailsSectionSerializer,
    DraftSessionSerializer,
    EvidenceCreateSerializer,
    EvidenceUpdateSerializer,
    ParticipantCreateSerializer,
    ParticipantUpdateSerializer,
    PoaHolderCreatedSerializer,
    PoaHolderCreateSerializer,
    PoaMandateSerializer,
    RepresentationSerializer,
    SignatureSerializer,
    SignedSerializer,
    WitnessCreateSerializer,
)
from .services import case_types, filing, participants, services

TAGS = ["cases"]


@extend_schema(tags=TAGS)
class CaseTypeListView(APIView):
    """GET /case-types — every case type and what it accepts."""

    @extend_schema(
        tags=TAGS,
        # Explicit: the default collides with the detail route's.
        operation_id="v1_case_types_list",
        responses={200: CaseTypeDescriptionSerializer(many=True)},
    )
    def get(self, request):
        """Return each case type's sections, document types and evidence schemas."""
        return Response(
            [case_types.get_description(case_type) for case_type in case_types.CASE_TYPES]
        )


@extend_schema(tags=TAGS)
class CaseTypeDetailView(APIView):
    """GET /case-types/{case_type} — what one case type accepts."""

    @extend_schema(tags=TAGS, responses={200: CaseTypeDescriptionSerializer})
    def get(self, request, case_type):
        """Return the case type's sections, document types and evidence schemas."""
        if case_type not in case_types.CASE_TYPES:
            raise NotFound("Unknown case type.")
        return Response(case_types.get_description(case_type))


# Filters are GET-only, so they are attached to ``get`` rather than the class.
@extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, description="Comma-separated statuses."),
            OpenApiParameter("created_by", str, enum=["me"]),
        ],
        responses=error_responses(
            api_errors.INVALID_CHOICE.example("Unknown status: CLOSED.", field="status"),
            api_errors.INVALID_CHOICE.example("Only 'me' is supported.", field="created_by"),
        ),
    )
)
class CaseListView(generics.ListAPIView):
    """GET /cases — the caller's cases. POST /cases — start a draft session."""

    serializer_class = CaseSerializer

    def get_queryset(self):
        """Return the caller's cases, optionally filtered by status."""
        params = self.request.query_params
        if params.get("created_by") not in (None, "me"):
            raise api_errors.INVALID_CHOICE.validation_error(
                {"created_by": ["Only 'me' is supported."]}
            )

        queryset = Case.objects.filter(created_by=self.request.user)
        if params.get("status"):
            statuses = params["status"].split(",")
            unknown = sorted(set(statuses) - set(CaseStatus.values))
            if unknown:
                raise api_errors.INVALID_CHOICE.validation_error(
                    {"status": [f"Unknown status: {', '.join(unknown)}."]}
                )
            queryset = queryset.filter(status__in=statuses)
        return queryset

    @extend_schema(
        tags=TAGS,
        request=DraftSessionSerializer,
        responses={
            201: DraftSessionSerializer,
            **error_responses(
                api_errors.DOES_NOT_EXIST.example("No active court with this id.", field="court_id")
            ),
        },
    )
    def post(self, request):
        """Start a draft session. No case is created until data is first saved."""
        serializer = DraftSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = services.start_draft(request.user, **serializer.validated_data)
        return Response(DraftSessionSerializer(draft).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS)
class CaseByNumberView(generics.RetrieveAPIView):
    """GET /cases/by-number/{case_number} — find a registered case to join.

    Open to any registered user, so it returns metadata only; cases that are
    not yet registered are not found.
    """

    serializer_class = CaseSerializer
    lookup_field = "case_number"
    queryset = Case.objects.filter(status__in=JOINABLE_STATUSES, case_number__isnull=False)


@extend_schema_view(
    get=extend_schema(tags=TAGS, parameters=[OpenApiParameter("document_type", str)])
)
class CaseDocumentListView(generics.ListAPIView):
    """GET /cases/{case_id}/documents — active documents. POST — upload one."""

    serializer_class = CaseDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        """Return the case's active documents, optionally of one type."""
        case = services.get_case(self.kwargs["case_id"], self.request.user)
        queryset = CaseDocument.objects.active().filter(case=case).select_related("document")
        if self.request.query_params.get("document_type"):
            queryset = queryset.filter(document_type=self.request.query_params["document_type"])
        return queryset

    @extend_schema(
        tags=TAGS,
        request=CaseDocumentUploadSerializer,
        responses={
            201: CaseDocumentSerializer,
            **error_responses(
                errors.NOT_ACCEPTED_FOR_CASE_TYPE.example(field="document_type"),
                errors.DOCUMENT_LINK_NOT_ALLOWED.example(
                    "Only an identity proof, vakalatnama or POA document belongs to a participant.",
                    field="case_participant_id",
                ),
                errors.WRONG_ROLE.example("Must be a complainant.", field="case_participant_id"),
                errors.PARTICIPANT_NOT_ON_CASE.example(field="case_participant_id"),
                errors.DOCUMENT_TYPE_MISMATCH.example(
                    "Must be a legal demand notice.", field="case_evidence_id"
                ),
                errors.EVIDENCE_NOT_ON_CASE.example(field="case_evidence_id"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Upload a case document; the first save on a draft creates the case.

        ``case_participant_id`` links an identity proof, vakalatnama or POA
        document to its party; ``case_evidence_id`` links a document to the
        evidence item it supports, such as a demand notice's proof of delivery.
        """
        serializer = CaseDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        document = services.add_document(
            case_id, request.user, data.pop("file"), data.pop("document_type"), **data
        )
        return Response(CaseDocumentSerializer(document).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS)
class CaseDocumentDetailView(APIView):
    """DELETE /case-documents/{case_document_id} — soft delete."""

    @extend_schema(tags=TAGS, responses={204: None, **error_responses(errors.CASE_NOT_EDITABLE)})
    def delete(self, request, case_document_id):
        """Remove a document from its case."""
        services.remove_document(case_document_id, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=TAGS)
class CaseDetailsView(APIView):
    """GET /cases/{case_id}/details — every details section."""

    # One key per section of the case's type, so the shape varies by case type;
    # GET /case-types/{case_type} lists the sections and their schemas.
    @extend_schema(tags=TAGS, responses={200: OpenApiTypes.OBJECT})
    def get(self, request, case_id):
        """Return the case's details, one key per section."""
        return Response(services.get_details(case_id, request.user))


@extend_schema(tags=TAGS)
class CaseDetailsSectionView(APIView):
    """PUT /cases/{case_id}/details/{section} — replace one section."""

    @extend_schema(
        tags=TAGS,
        # The body is the section object; its schema depends on the case type and
        # section, and is served by GET /case-types/{case_type}.
        request=OpenApiTypes.OBJECT,
        responses={
            200: DetailsSectionSerializer,
            **error_responses(
                errors.NOT_ACCEPTED_FOR_CASE_TYPE.example(field="section"),
                api_errors.INCORRECT_TYPE.example("Expected a JSON object.", field="data"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def put(self, request, case_id, section):
        """Replace a section; the first save on a draft creates the case."""
        if not isinstance(request.data, dict):
            raise api_errors.INCORRECT_TYPE.validation_error({"data": ["Expected a JSON object."]})
        case = services.save_details_section(case_id, request.user, section, request.data)
        return Response({"case_id": case.id, "section": section, "data": request.data})


@extend_schema_view(
    get=extend_schema(tags=TAGS, parameters=[OpenApiParameter("evidence_type", str)])
)
class CaseEvidenceListView(generics.ListAPIView):
    """GET /cases/{case_id}/evidence — active evidence. POST — add evidence."""

    serializer_class = CaseEvidenceSerializer

    def get_queryset(self):
        """Return the case's active evidence, optionally of one type."""
        case = services.get_case(self.kwargs["case_id"], self.request.user)
        queryset = CaseEvidence.objects.active().filter(case=case).order_by(*EVIDENCE_ORDERING)
        if self.request.query_params.get("evidence_type"):
            queryset = queryset.filter(evidence_type=self.request.query_params["evidence_type"])
        return queryset

    @extend_schema(
        tags=TAGS,
        request=EvidenceCreateSerializer,
        responses={
            201: CaseEvidenceSerializer,
            **error_responses(
                errors.NOT_ACCEPTED_FOR_CASE_TYPE.example(field="evidence_type"),
                errors.DOCUMENT_NOT_ON_CASE.example(field="case_document_id"),
                errors.DOCUMENT_TYPE_MISMATCH.example(
                    "Must be a bounced cheque document.", field="case_document_id"
                ),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Add evidence; the first save on a draft creates the case."""
        serializer = EvidenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        evidence = services.add_evidence(case_id, request.user, **serializer.validated_data)
        return Response(CaseEvidenceSerializer(evidence).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS)
class CaseEvidenceDetailView(APIView):
    """PATCH or DELETE /case-evidence/{case_evidence_id}."""

    @extend_schema(
        tags=TAGS,
        request=EvidenceUpdateSerializer,
        responses={
            200: CaseEvidenceSerializer,
            **error_responses(
                errors.DOCUMENT_NOT_ON_CASE.example(field="case_document_id"),
                errors.DOCUMENT_TYPE_MISMATCH.example(
                    "Must be a bounced cheque document.", field="case_document_id"
                ),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def patch(self, request, case_evidence_id):
        """Replace ``evidence_info`` and/or link or unlink a document."""
        evidence = services.get_evidence(case_evidence_id, request.user)
        serializer = EvidenceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        evidence = services.update_evidence(evidence, request.user, **serializer.validated_data)
        return Response(CaseEvidenceSerializer(evidence).data)

    @extend_schema(tags=TAGS, responses={204: None, **error_responses(errors.CASE_NOT_EDITABLE)})
    def delete(self, request, case_evidence_id):
        """Remove evidence from its case."""
        evidence = services.get_evidence(case_evidence_id, request.user)
        services.remove_evidence(evidence, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class _ParticipantCreateView(APIView):
    """Adds a party in ``role``; the first save on a draft creates the case."""

    role = None

    @extend_schema(
        tags=TAGS,
        request=ParticipantCreateSerializer,
        responses={
            201: CaseParticipantSerializer,
            **error_responses(
                api_errors.REQUIRED.example(ADDRESS_REQUIRED_MESSAGE, field="address"),
                errors.PERSON_AND_SELF.example(field="self"),
                errors.SELF_AS_ACCUSED.example(field="self"),
                errors.INSTITUTION_NOT_ALLOWED.example(field="institution"),
                errors.ROLE_ALREADY_HELD.example(
                    "This person is already a complainant on this case.", field="person"
                ),
                errors.BOTH_SIDES.example(
                    "A person cannot be both a complainant and an accused on a case.",
                    field="person",
                ),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Add the party; send ``person``, ``"self": true`` or ``institution``."""
        serializer = ParticipantCreateSerializer(data=request.data, context={"role": self.role})
        serializer.is_valid(raise_exception=True)
        participant = participants.add_participant(
            case_id, request.user, self.role, serializer.validated_data
        )
        return Response(CaseParticipantSerializer(participant).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS)
class ComplainantCreateView(_ParticipantCreateView):
    """POST /cases/{case_id}/complainants — add a complainant."""

    role = ParticipantRole.COMPLAINANT


@extend_schema(tags=TAGS)
class AccusedCreateView(_ParticipantCreateView):
    """POST /cases/{case_id}/accused — add an accused. ``self`` is not accepted."""

    role = ParticipantRole.ACCUSED


@extend_schema(tags=TAGS)
class WitnessCreateView(APIView):
    """POST /cases/{case_id}/witnesses — add a witness; the first save on a draft creates the case."""

    @extend_schema(
        tags=TAGS,
        request=WitnessCreateSerializer,
        responses={
            201: CaseParticipantSerializer,
            **error_responses(
                errors.WITNESS_ALREADY_CALLED.example(field="side"),
                errors.PERSON_AND_SELF.example(field="self"),
                errors.FIELD_NOT_ACCEPTED.example(field="institution"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Add the witness; send ``person`` or ``"self": true``, and which side calls them."""
        serializer = WitnessCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        participant = participants.add_witness(case_id, request.user, serializer.validated_data)
        return Response(CaseParticipantSerializer(participant).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("role", str, enum=ParticipantRole.values)],
        responses={
            200: CaseParticipantSerializer(many=True),
            **error_responses(
                api_errors.INVALID_CHOICE.example("Unknown role: JUDGE.", field="role")
            ),
        },
    )
)
class CaseParticipantListView(generics.ListAPIView):
    """GET /cases/{case_id}/participants — active participants, by role then ordinal."""

    serializer_class = CaseParticipantSerializer

    def get_queryset(self):
        """Return the case's active participants, optionally of one role."""
        case = services.get_case(self.kwargs["case_id"], self.request.user)
        queryset = (
            CaseParticipant.objects.active()
            .filter(case=case)
            .select_related("witness")
            .order_by(*PARTICIPANT_ORDERING)
        )
        role = self.request.query_params.get("role")
        if role:
            if role not in ParticipantRole.values:
                raise api_errors.INVALID_CHOICE.validation_error(
                    {"role": [f"Unknown role: {role}."]}
                )
            queryset = queryset.filter(role=role)
        return queryset


@extend_schema(tags=TAGS)
class CaseParticipantDetailView(APIView):
    """PATCH or DELETE /case-participants/{case_participant_id}."""

    @extend_schema(
        tags=TAGS,
        request=ParticipantUpdateSerializer,
        responses={
            200: CaseParticipantSerializer,
            **error_responses(
                errors.FIELD_NOT_ACCEPTED.example("This field cannot be changed.", field="role"),
                errors.FIELD_NOT_APPLICABLE.example(
                    "Only for a witness.", field="what_will_witness_prove"
                ),
                errors.PARTY_IN_PERSON.example(
                    "Remove this party's advocates first.", field="is_party_in_person"
                ),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def patch(self, request, case_participant_id):
        """Change the case's copy of the party's details; never the person or institution."""
        participant = participants.get_participant(case_participant_id, request.user)
        serializer = ParticipantUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        participant = participants.update_participant(
            participant, request.user, serializer.validated_data
        )
        return Response(CaseParticipantSerializer(participant).data)

    @extend_schema(
        tags=TAGS,
        responses={204: None, **error_responses(errors.CASE_NOT_EDITABLE)},
    )
    def delete(self, request, case_participant_id):
        """Remove the party; the rest of the role is renumbered."""
        participant = participants.get_participant(case_participant_id, request.user)
        participants.remove_participant(participant, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=TAGS)
class PoaHolderCreateView(APIView):
    """POST /cases/{case_id}/poa-holders — add a POA holder and their mandates."""

    @extend_schema(
        tags=TAGS,
        request=PoaHolderCreateSerializer,
        responses={
            201: PoaHolderCreatedSerializer,
            **error_responses(
                api_errors.REQUIRED.example(ADDRESS_REQUIRED_MESSAGE, field="address"),
                errors.DUPLICATE_PARTICIPANT.example(field="represented_participant_ids"),
                errors.PARTICIPANT_NOT_ON_CASE.example(
                    "Must be active participants of the same case.",
                    field="represented_participant_ids",
                ),
                errors.WRONG_ROLE.example(field="represented_participant_ids"),
                errors.SELF_REPRESENTATION.example(
                    "A person cannot hold a mandate for themselves.",
                    field="represented_participant_ids",
                ),
                errors.PERSON_AND_SELF.example(field="self"),
                errors.FIELD_NOT_ACCEPTED.example(field="institution"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Add the holder; send ``person`` or ``"self": true``, and the parties they act for."""
        serializer = PoaHolderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        holder, mandates = participants.add_poa_holder(
            case_id, request.user, serializer.validated_data
        )
        body = {
            "case_participant_id": holder.id,
            "poa_mandate_ids": [mandate.id for mandate in mandates],
            "person_id": holder.person_id,
            "role": holder.role,
        }
        return Response(PoaHolderCreatedSerializer(body).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        responses={200: PoaMandateSerializer(many=True)},
    )
)
class PoaMandateListView(generics.ListAPIView):
    """GET /cases/{case_id}/poa-mandates — active mandates, by holder then represented party."""

    serializer_class = PoaMandateSerializer

    def get_queryset(self):
        """Return the case's active mandates."""
        case = services.get_case(self.kwargs["case_id"], self.request.user)
        return (
            PoaMandate.objects.active()
            .filter(case=case)
            .select_related("poa_participant")
            .order_by(*POA_MANDATE_ORDERING)
        )


@extend_schema(tags=TAGS)
class PoaMandateDetailView(APIView):
    """DELETE /poa-mandates/{poa_mandate_id}."""

    @extend_schema(tags=TAGS, responses={204: None, **error_responses(errors.CASE_NOT_EDITABLE)})
    def delete(self, request, poa_mandate_id):
        """Revoke the mandate; a holder left acting for no one is removed too."""
        mandate = participants.get_mandate(poa_mandate_id, request.user)
        participants.revoke_mandate(mandate, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=TAGS)
class AdvocateCreateView(APIView):
    """POST /cases/{case_id}/advocates — add an advocate for one or more clients."""

    @extend_schema(
        tags=TAGS,
        request=AdvocateCreateSerializer,
        responses={
            201: AdvocateCreatedSerializer,
            **error_responses(
                api_errors.DOES_NOT_EXIST.example("Advocate not found.", field="advocate_id"),
                errors.DUPLICATE_PARTICIPANT.example(field="client_participant_ids"),
                errors.PARTICIPANT_NOT_ON_CASE.example(
                    "Must be active participants of the same case.",
                    field="client_participant_ids",
                ),
                errors.ADVOCATE_NOT_APPROVED.example(field="advocate"),
                errors.WRONG_ROLE.example(field="client_participant_ids"),
                errors.PARTY_IN_PERSON.example(field="client_participant_ids"),
                errors.SELF_REPRESENTATION.example(
                    "An advocate cannot represent themselves.", field="client_participant_ids"
                ),
                errors.BOTH_SIDES.example(
                    "An advocate cannot represent both a complainant and an accused.",
                    field="client_participant_ids",
                ),
                errors.ALREADY_ACTING.example(
                    "This advocate already represents this party.",
                    field="client_participant_ids",
                ),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Create one representation per client, all for the same advocate."""
        serializer = AdvocateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        representations = participants.add_advocate(
            case_id, request.user, serializer.validated_data
        )
        body = {
            "representation_ids": [representation.id for representation in representations],
            "advocate_id": serializer.validated_data["advocate_id"],
        }
        return Response(AdvocateCreatedSerializer(body).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        responses={200: RepresentationSerializer(many=True)},
    )
)
class RepresentationListView(generics.ListAPIView):
    """GET /cases/{case_id}/representations — active representations, by client."""

    serializer_class = RepresentationSerializer

    def get_queryset(self):
        """Return the case's active representations."""
        case = services.get_case(self.kwargs["case_id"], self.request.user)
        return (
            Representation.objects.active()
            .filter(case=case)
            .select_related("advocate")
            .order_by(*REPRESENTATION_ORDERING)
        )


@extend_schema(tags=TAGS)
class RepresentationDetailView(APIView):
    """DELETE /representations/{representation_id}."""

    @extend_schema(tags=TAGS, responses={204: None, **error_responses(errors.CASE_NOT_EDITABLE)})
    def delete(self, request, representation_id):
        """End the representation; the row is kept."""
        representation = participants.get_representation(representation_id, request.user)
        participants.end_representation(representation, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Preview, validation, status transitions and signing (spec 0021 §6–8)


@extend_schema(tags=TAGS)
class CasePreviewView(APIView):
    """GET /cases/{case_id} — the whole filing, as the case recorded it."""

    @extend_schema(tags=TAGS, responses={200: CasePreviewSerializer})
    def get(self, request, case_id):
        """Return the case with everything active on it, and its details sections."""
        return Response(filing.get_preview(case_id, request.user))


@extend_schema(tags=TAGS)
class CaseValidateView(APIView):
    """POST /cases/{case_id}/validate — the completeness check."""

    @extend_schema(tags=TAGS, request=None, responses={200: CaseValidationSerializer})
    def post(self, request, case_id):
        """Return whether the filing is complete and, if not, everything that is missing."""
        is_valid, problems = filing.validate_case(case_id, request.user)
        return Response(CaseValidationSerializer({"is_valid": is_valid, "errors": problems}).data)


def _transition_schema(*step_errors):
    """Document a transition: the case it returns, and the errors its step adds."""
    return extend_schema_view(
        post=extend_schema(
            tags=TAGS,
            request=None,
            responses={
                200: CaseSerializer,
                **error_responses(errors.INVALID_STATUS_TRANSITION, *step_errors),
            },
        )
    )


class _CaseTransitionView(APIView):
    """Moves the case one step along its lifecycle; ``transition`` does the work."""

    transition = None

    def post(self, request, case_id):
        """Advance the case and return it."""
        case = type(self).transition(case_id, request.user)
        return Response(CaseSerializer(case).data)


@_transition_schema(
    errors.FILING_INCOMPLETE.example(
        "At least one active accused is required.", field="participants.accused"
    )
)
class SubmitForSigningView(_CaseTransitionView):
    """POST /cases/{case_id}/submit-for-signing — a complete draft moves to PENDING_SIGN."""

    transition = filing.submit_for_signing


@_transition_schema(
    errors.SIGNATURES_PENDING.example("Complainant #1 has not signed.", field="participants.<id>")
)
class SubmitForPaymentView(_CaseTransitionView):
    """POST /cases/{case_id}/submit-for-payment — once every signer has signed."""

    transition = filing.submit_for_payment


@_transition_schema()
class SubmitForScrutinyView(_CaseTransitionView):
    """POST /cases/{case_id}/submit-for-scrutiny — the case is filed and goes to scrutiny."""

    transition = filing.submit_for_scrutiny


@extend_schema(tags=TAGS)
class ParticipantSignView(APIView):
    """POST /cases/{case_id}/participants/{case_participant_id}/sign — record a signature."""

    @extend_schema(
        tags=TAGS,
        request=SignatureSerializer,
        responses={
            200: SignedSerializer,
            **error_responses(
                errors.NOT_A_SIGNER.example(field="case_participant_id"),
                errors.SIGNATURE_NOT_FOUND.example(field="signature_document_id"),
                errors.SIGNATURE_ALREADY_USED.example(field="signature_document_id"),
                errors.SIGNED_BY_SOMEONE_ELSE.example(field="signature_document_id"),
                errors.SIGNED_BEFORE_SUBMISSION.example(field="signature_document_id"),
                errors.INVALID_STATUS_TRANSITION,
                errors.ALREADY_SIGNED,
            ),
        },
    )
    def post(self, request, case_id, case_participant_id):
        """Record the participant's e-signature on the filing."""
        serializer = SignatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        participant = filing.record_signature(
            case_id,
            case_participant_id,
            request.user,
            serializer.validated_data["signature_document_id"],
        )
        return Response(SignedSerializer(participant).data)

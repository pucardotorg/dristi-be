"""Scrutiny, registration and filer-correction API views (spec 0024 #8).

Views stay thin: each finds the case for the caller (``permissions``), hands
the action to a service or the read to ``selectors``, and renders the result.
Court actions check the caller's role in the service; decisions take
``If-Match: <workflow_version>`` and refuse a stale one with ``412 E08005``.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.errors import BusinessError
from apps.api.schema import error_responses

from . import errors, permissions, ports, selectors
from .enums import RoundStage
from .serializers import (
    CorrectionsSerializer,
    ExplainSerializer,
    FlagCreateSerializer,
    FlagResponseSerializer,
    FlagSerializer,
    FlagUpdateSerializer,
    HistorySerializer,
    MoveOnSerializer,
    RegisterSerializer,
    RegistrationDetailSerializer,
    RegistrationListQuerySerializer,
    RegistrationRowSerializer,
    RegistrationSendBackSerializer,
    ResubmittedSerializer,
    RoundSerializer,
    ScrutinyDecisionSerializer,
    ScrutinyDetailSerializer,
    ScrutinyListQuerySerializer,
    ScrutinyRowSerializer,
    TitleResultSerializer,
    TitleSerializer,
)
from .services import flags, responses, rounds

UUID_PATTERN = "[0-9a-fA-F-]{36}"

IF_MATCH = OpenApiParameter(
    "If-Match",
    OpenApiTypes.INT,
    location=OpenApiParameter.HEADER,
    required=False,
    description="The detail's `workflow_version`; a stale one is refused with 412 E08005.",
)

# Errors every court action on an open round can give.
ROUND_ERRORS = (errors.ROUND_NOT_OPEN, errors.ROLE_REQUIRED)
DECISION_ERRORS = (*ROUND_ERRORS, ports.WORKFLOW_STALE)
MOVE_ON_ERRORS = (
    *DECISION_ERRORS,
    errors.ACTION_NOT_FOR_ROLES,
    errors.COURTROOM_REQUIRED.example(field="courtroom_id"),
    errors.REGISTRATION_TYPE_REQUIRED.example(field="registration_type"),
    errors.OPEN_ITEMS_NOT_ACKNOWLEDGED,
)


class TabCountPagination(PageNumberPagination):
    """Page-number pagination that also returns the count of every tab (#7.1)."""

    counts = None

    def get_paginated_response(self, data):
        """Add ``counts`` after ``count``."""
        response = super().get_paginated_response(data)
        response.data = {
            "count": response.data.pop("count"),
            "counts": self.counts,
            **response.data,
        }
        return response

    def get_paginated_response_schema(self, schema):
        """Document ``counts``."""
        schema = super().get_paginated_response_schema(schema)
        schema["properties"] = {
            "counts": {
                "type": "object",
                "properties": {tab: {"type": "integer"} for tab in selectors.TABS},
            },
            **schema["properties"],
        }
        return schema


def _valid(serializer_class, data, **kwargs):
    serializer = serializer_class(data=data, **kwargs)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def expected_version(request):
    """Return the ``If-Match`` version, or None. ETag quoting (``"9"``, ``W/"9"``) is accepted."""
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip().removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise BusinessError(ports.WORKFLOW_STALE) from exc


def _versioned(data, version):
    return Response(data, headers={"ETag": f'"{version}"'})


def _decided(round_):
    case = round_.case
    case.refresh_from_db()
    version = ports.workflow_version(case)
    data = ScrutinyDecisionSerializer(
        {
            "round": round_,
            "case_status": case.status,
            "case_number": case.case_number,
            "workflow_version": version,
        }
    ).data
    return _versioned(data, version)


class ScrutinyViewSet(viewsets.GenericViewSet):
    """The Scrutiny officer's list, detail, flags and decisions (#8.1)."""

    lookup_field = "case_id"
    lookup_value_regex = UUID_PATTERN
    serializer_class = ScrutinyRowSerializer
    pagination_class = TabCountPagination
    unpaginated_actions = {"flags"}

    @extend_schema(
        parameters=[ScrutinyListQuerySerializer], responses=error_responses(errors.ROLE_REQUIRED)
    )
    def list(self, request):
        """Filings of the establishment, by tab: with registry, with advocate, closed."""
        query = _valid(ScrutinyListQuerySerializer, request.query_params)
        permissions.require_court_reader(request.user, query["establishment"])
        found = selectors.scrutiny_list(
            request.user,
            tab=query["tab"],
            claimed=query["claimed"],
            search=query["search"],
            establishment_id=query["establishment"],
        )
        page = self.paginate_queryset(found["rounds"])
        self.paginator.counts = found["counts"]
        rows = selectors.scrutiny_rows(page)
        return self.get_paginated_response(ScrutinyRowSerializer(rows, many=True).data)

    @extend_schema(responses=ScrutinyDetailSerializer)
    def retrieve(self, request, case_id=None):
        """One filing: fields, bundle, alerts, flags and what the caller may do."""
        case, round_ = permissions.court_case(case_id, request.user)
        detail = selectors.scrutiny_detail(case, round_, request.user)
        return _versioned(ScrutinyDetailSerializer(detail).data, detail["workflow_version"])

    @extend_schema(responses=HistorySerializer)
    @action(detail=True, methods=["get"])
    def history(self, request, case_id=None):
        """The rounds of the case and what became of each item (#7.5)."""
        case, _round = permissions.court_case(case_id, request.user)
        return Response(HistorySerializer(selectors.history(case)).data)

    @extend_schema(request=None, responses={200: RoundSerializer, **error_responses(*ROUND_ERRORS)})
    @action(detail=True, methods=["post"])
    def start(self, request, case_id=None):
        """Start, or take over, the open scrutiny round (#4.2)."""
        permissions.court_case(case_id, request.user)
        round_ = rounds.start(case_id, request.user, RoundStage.SCRUTINY)
        return Response(RoundSerializer(round_).data)

    @extend_schema(
        request=FlagCreateSerializer,
        responses={
            201: FlagSerializer,
            **error_responses(
                *ROUND_ERRORS,
                errors.FLAG_TARGET_UNKNOWN.example(field="target_ref"),
                errors.FLAG_NOTE_REQUIRED.example(field="note"),
                errors.FLAG_DUPLICATE.example(field="target_ref"),
                errors.GENERATED_DOCUMENT_NOT_FLAGGABLE.example(field="target_ref"),
                errors.OATH_NOT_REQUIRED.example(field="target_ref"),
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def flags(self, request, case_id=None):
        """Draft a flag; returns every flag created, with the dates it marked (#3.3)."""
        permissions.court_case(case_id, request.user)
        data = _valid(FlagCreateSerializer, request.data)
        issue = data["document_issue"]
        created = flags.draft(
            case_id,
            request.user,
            target_type=data["target_type"],
            target_ref=data["target_ref"],
            note=data["note"],
            reason_code=data["reason_code"],
            document_issue={**issue, "document_id": str(issue["document_id"])} if issue else None,
        )
        views = [selectors.flag_view(flag) for flag in created]
        return Response(FlagSerializer(views, many=True).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        methods=["PATCH"],
        request=FlagUpdateSerializer,
        responses={
            200: FlagSerializer,
            **error_responses(
                *ROUND_ERRORS,
                errors.FLAG_NOT_DRAFT,
                errors.FLAG_NOTE_REQUIRED.example(field="note"),
            ),
        },
    )
    @extend_schema(
        methods=["DELETE"],
        request=None,
        responses={204: None, **error_responses(*ROUND_ERRORS, errors.FLAG_NOT_DRAFT)},
    )
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=rf"flags/(?P<flag_id>{UUID_PATTERN})",
        url_name="flag",
    )
    def flag(self, request, case_id=None, flag_id=None):
        """Edit a draft's note or reason, or withdraw it."""
        permissions.court_case(case_id, request.user)
        if request.method == "DELETE":
            flags.withdraw(case_id, flag_id, request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)
        data = _valid(FlagUpdateSerializer, request.data)
        flag = flags.edit(
            case_id,
            flag_id,
            request.user,
            note=data.get("note"),
            reason_code=data.get("reason_code"),
        )
        return Response(FlagSerializer(selectors.flag_view(flag)).data)

    @extend_schema(
        request=None,
        responses={200: FlagSerializer, **error_responses(*ROUND_ERRORS, errors.FLAG_NOT_DRAFT)},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=rf"flags/(?P<flag_id>{UUID_PATTERN})/resolve",
        url_name="flag-resolve",
    )
    def resolve(self, request, case_id=None, flag_id=None):
        """Resolve an item carried from an earlier round, with all its earlier copies (#4.5)."""
        permissions.court_case(case_id, request.user)
        flag = flags.resolve(case_id, flag_id, request.user)
        return Response(FlagSerializer(selectors.flag_view(flag)).data)

    @extend_schema(
        request=None,
        parameters=[IF_MATCH],
        responses={
            200: ScrutinyDecisionSerializer,
            **error_responses(*DECISION_ERRORS, errors.NOTHING_TO_SEND_BACK),
        },
    )
    @action(detail=True, methods=["post"], url_path="send-back")
    def send_back(self, request, case_id=None):
        """Raise every draft and send the case to the filer (#4.3)."""
        permissions.court_case(case_id, request.user)
        round_ = rounds.send_back(case_id, request.user, expected_version=expected_version(request))
        return _decided(round_)

    @extend_schema(
        request=MoveOnSerializer,
        parameters=[IF_MATCH],
        responses={200: ScrutinyDecisionSerializer, **error_responses(*MOVE_ON_ERRORS)},
    )
    @action(detail=True, methods=["post"])
    def forward(self, request, case_id=None):
        """Forward to the Case registerer; for a Scrutiny officer who does not register (#4.4)."""
        return self._move_on(request, case_id, rounds.forward)

    @extend_schema(
        request=MoveOnSerializer,
        parameters=[IF_MATCH],
        responses={200: ScrutinyDecisionSerializer, **error_responses(*MOVE_ON_ERRORS)},
    )
    @action(detail=True, methods=["post"])
    def register(self, request, case_id=None):
        """Register at Scrutiny; for a Scrutiny officer who is also a Case registerer (#4.4)."""
        return self._move_on(request, case_id, rounds.register_at_scrutiny)

    def _move_on(self, request, case_id, decide):
        permissions.court_case(case_id, request.user)
        data = _valid(MoveOnSerializer, request.data)
        round_ = decide(
            case_id,
            request.user,
            courtroom_id=data["courtroom_id"],
            registration_type=data["registration_type"],
            acknowledge_open_items=data["acknowledge_open_items"],
            expected_version=expected_version(request),
        )
        return _decided(round_)

    @extend_schema(
        request=TitleSerializer,
        responses={200: TitleResultSerializer, **error_responses(*ROUND_ERRORS)},
    )
    @action(detail=True, methods=["patch"])
    def title(self, request, case_id=None):
        """Change the parties' names shown on the case (*Edit case title*, #4.6)."""
        permissions.court_case(case_id, request.user)
        data = _valid(TitleSerializer, request.data)
        rounds.set_title(case_id, request.user, **data)
        return Response(TitleResultSerializer(data).data)


@extend_schema(tags=["registration"])
class RegistrationViewSet(viewsets.GenericViewSet):
    """The Case registerer's list, detail and decisions (#8.2)."""

    lookup_field = "case_id"
    lookup_value_regex = UUID_PATTERN
    serializer_class = RegistrationRowSerializer

    @extend_schema(
        parameters=[RegistrationListQuerySerializer],
        responses=error_responses(errors.ROLE_REQUIRED),
    )
    def list(self, request):
        """Forwarded cases waiting to be registered, longest waiting first."""
        query = _valid(RegistrationListQuerySerializer, request.query_params)
        permissions.require_court_reader(request.user, query["establishment"])
        found = selectors.registration_list(
            request.user,
            search=query["search"],
            ordering=query["ordering"],
            establishment_id=query["establishment"],
        )
        page = self.paginate_queryset(found)
        rows = selectors.registration_rows(page)
        return self.get_paginated_response(RegistrationRowSerializer(rows, many=True).data)

    @extend_schema(responses=RegistrationDetailSerializer)
    def retrieve(self, request, case_id=None):
        """A forwarded case: summary, scrutiny, timeline and open items (#7.4)."""
        case, round_ = permissions.court_case(case_id, request.user)
        detail = selectors.registration_detail(case, round_, request.user)
        return _versioned(RegistrationDetailSerializer(detail).data, detail["workflow_version"])

    @extend_schema(request=None, responses={200: RoundSerializer, **error_responses(*ROUND_ERRORS)})
    @action(detail=True, methods=["post"])
    def start(self, request, case_id=None):
        """Start, or take over, the open registration round."""
        permissions.court_case(case_id, request.user)
        round_ = rounds.start(case_id, request.user, RoundStage.REGISTRATION)
        return Response(RoundSerializer(round_).data)

    @extend_schema(
        request=RegisterSerializer,
        parameters=[IF_MATCH],
        responses={
            200: ScrutinyDecisionSerializer,
            **error_responses(
                *DECISION_ERRORS,
                errors.REGISTRATION_TYPE_REQUIRED.example(field="registration_type"),
                errors.OPEN_ITEMS_NOT_ACKNOWLEDGED,
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def register(self, request, case_id=None):
        """Register the case; the type chosen at Forward is kept unless changed (#6.1)."""
        permissions.court_case(case_id, request.user)
        data = _valid(RegisterSerializer, request.data)
        round_ = rounds.register(
            case_id,
            request.user,
            registration_type=data["registration_type"],
            acknowledge_open_items=data["acknowledge_open_items"],
            expected_version=expected_version(request),
        )
        return _decided(round_)

    @extend_schema(
        request=RegistrationSendBackSerializer,
        parameters=[IF_MATCH],
        responses={
            200: ScrutinyDecisionSerializer,
            **error_responses(
                *DECISION_ERRORS,
                errors.SEND_BACK_COMMENT_REQUIRED.example(field="comment"),
                errors.SEND_BACK_COMMENT_REQUIRED.example(field="flags"),
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="send-back")
    def send_back(self, request, case_id=None):
        """Send the case to the filer with one comment; everything but the oath opens (#6.2)."""
        permissions.court_case(case_id, request.user)
        data = _valid(RegistrationSendBackSerializer, request.data)
        round_ = rounds.registration_send_back(
            case_id, request.user, data["comment"], expected_version=expected_version(request)
        )
        return _decided(round_)


# The filing side (#8.3)


class CorrectionsView(APIView):
    """GET /cases/{case_id}/corrections/ — what the latest send back asks for (#7.6)."""

    @extend_schema(responses=CorrectionsSerializer)
    def get(self, request, case_id):
        """The raised items, grouped as the screen groups them, or the registerer's comment."""
        case = permissions.filing_case(case_id, request.user)
        return Response(CorrectionsSerializer(selectors.corrections(case)).data)


class CorrectionExplainView(APIView):
    """POST /cases/{case_id}/corrections/{flag_id}/explain/ — answer without a change (#5.2)."""

    @extend_schema(
        request=ExplainSerializer,
        responses={
            201: FlagResponseSerializer,
            **error_responses(
                errors.ROUND_NOT_OPEN, errors.EXPLANATION_REQUIRED.example(field="note")
            ),
        },
    )
    def post(self, request, case_id, flag_id):
        """Explain a raised item; the court sees it as contested."""
        permissions.filing_case(case_id, request.user)
        data = _valid(ExplainSerializer, request.data)
        response = responses.explain(case_id, flag_id, request.user, data["note"])
        return Response(
            FlagResponseSerializer(selectors.response_view(response)).data,
            status=status.HTTP_201_CREATED,
        )


class CorrectionSubmitView(APIView):
    """POST /cases/{case_id}/corrections/submit/ — resubmit the corrected case (#5.3)."""

    @extend_schema(
        request=None,
        responses={
            200: ResubmittedSerializer,
            **error_responses(errors.ROUND_NOT_OPEN, errors.NOTHING_TO_RESUBMIT),
        },
    )
    def post(self, request, case_id):
        """Send the case to be signed again; unanswered items travel to re-scrutiny."""
        permissions.filing_case(case_id, request.user)
        case = responses.submit_correction(case_id, request.user)
        return Response(
            ResubmittedSerializer(
                {"case_status": case.status, "workflow_version": ports.workflow_version(case)}
            ).data
        )


class FilerHistoryView(APIView):
    """GET /cases/{case_id}/scrutiny-history/ — the round timeline, for the filing side (#7.5)."""

    @extend_schema(responses=HistorySerializer)
    def get(self, request, case_id):
        """The rounds and items, without court staff names."""
        case = permissions.filing_case(case_id, request.user)
        return Response(HistorySerializer(selectors.history(case, for_filer=True)).data)

"""Tests for draft sessions and lazy case creation (spec 0021 §9.1)."""

import threading
import uuid
from unittest.mock import patch

import pytest
from django.db import connection, transaction
from rest_framework.exceptions import NotFound

from apps.cases.models import Case, CaseEvidence, ChequeBounceCase, EvidenceType
from apps.cases.services import services

from .conftest import CHEQUE_INFO


def create_from(draft, user):
    with transaction.atomic():
        return services.get_or_create_case(draft, user)


@pytest.mark.django_db
class TestDraftSessions:
    def test_starting_a_draft_writes_nothing_to_the_database(self, user, draft):
        assert Case.objects.count() == 0

    def test_first_save_creates_the_case_and_its_detail_row(self, user, draft):
        case = create_from(draft, user)

        assert str(case.pk) == draft
        assert case.created_by == user
        assert case.status == "DRAFT_IN_PROGRESS"
        assert ChequeBounceCase.objects.get(case=case).jurisdiction_limitation == {}

    def test_later_saves_reuse_the_case(self, user, draft):
        first = create_from(draft, user)
        second = create_from(draft, user)

        assert first == second
        assert Case.objects.count() == ChequeBounceCase.objects.count() == 1

    def test_draft_is_dropped_once_the_case_commits(
        self, user, draft, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            create_from(draft, user)

        assert services._get_owned_draft(draft, user) is None
        assert create_from(draft, user).pk == uuid.UUID(draft)

    def test_concurrent_first_save_gets_the_case_the_other_created(self, user, draft):
        # The other request created the case after this one looked for it.
        create_from(draft, user)
        with patch.object(services, "_get_owned_case", return_value=None):
            case = create_from(draft, user)

        assert str(case.pk) == draft
        assert Case.objects.count() == ChequeBounceCase.objects.count() == 1

    def test_another_users_draft_is_not_found(self, other_user, draft):
        with pytest.raises(NotFound):
            create_from(draft, other_user)
        assert Case.objects.count() == 0

    def test_unknown_id_is_not_found(self, user):
        with pytest.raises(NotFound):
            create_from(uuid.uuid4(), user)

    def test_failed_first_save_creates_no_case(self, user, draft):
        with pytest.raises(Exception, match="boom"), transaction.atomic():
            services.get_or_create_case(draft, user)
            raise RuntimeError("boom")

        assert Case.objects.count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="needs row-level locking (run against Postgres)"
)
def test_concurrent_first_saves_create_exactly_one_case(user, draft):
    results, errors = [], []
    barrier = threading.Barrier(5)

    def first_save():
        try:
            barrier.wait()
            evidence = services.add_evidence(
                draft, user, evidence_type=EvidenceType.CHEQUE, evidence_info=CHEQUE_INFO
            )
            results.append(evidence.case_id)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=first_save) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert {str(case_id) for case_id in results} == {draft}
    assert Case.objects.count() == ChequeBounceCase.objects.count() == 1
    assert sorted(CaseEvidence.objects.values_list("ordinal", flat=True)) == [1, 2, 3, 4, 5]

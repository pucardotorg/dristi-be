"""Routing contract for the dristi requests API.

Pins the public paths so a router or mount change cannot silently move them,
and checks that only UUIDs are read as ids now that requests are mounted at
the prefix root.
"""

import uuid

import pytest
from django.urls import Resolver404, resolve, reverse

PREFIX = "/api/v1/dristi-requests"
ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
DOC = uuid.UUID("66666666-7777-8888-9999-000000000000")


@pytest.mark.parametrize(
    ("name", "args", "path"),
    [
        ("request-approval-list", [], "/approvals/"),
        ("request-approval-detail", [ID], f"/approvals/{ID}/"),
        ("request-approval-decide", [ID], f"/approvals/{ID}/decide/"),
        ("request-type-list", [], "/request-types/"),
        ("request-type-detail", [ID], f"/request-types/{ID}/"),
        ("request-list", [], "/"),
        ("request-detail", [ID], f"/{ID}/"),
        ("request-approvals", [ID], f"/{ID}/approvals/"),
        ("request-cancel", [ID], f"/{ID}/cancel/"),
        ("request-resubmit", [ID], f"/{ID}/resubmit/"),
        ("request-document-download", [ID, DOC], f"/{ID}/documents/{DOC}/"),
    ],
)
def test_public_paths(name, args, path):
    assert reverse(name, args=args) == f"{PREFIX}{path}"


@pytest.mark.parametrize(
    ("path", "name", "kwarg"),
    [
        (f"/approvals/{ID}/", "request-approval-detail", "approval_id"),
        (f"/request-types/{ID}/", "request-type-detail", "request_type_id"),
        (f"/{ID}/", "request-detail", "request_id"),
    ],
)
def test_path_parameters_are_named_for_their_resource(path, name, kwarg):
    match = resolve(f"{PREFIX}{path}")

    assert match.url_name == name
    assert match.kwargs == {kwarg: str(ID)}


@pytest.mark.parametrize("prefix", ["approvals", "request-types"])
def test_sibling_prefixes_are_not_read_as_request_ids(prefix):
    assert resolve(f"{PREFIX}/{prefix}/").url_name != "request-detail"


@pytest.mark.parametrize("segment", ["not-a-uuid", "requests", "123"])
def test_non_uuid_ids_do_not_resolve(segment):
    with pytest.raises(Resolver404):
        resolve(f"{PREFIX}/{segment}/")

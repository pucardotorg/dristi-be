"""Filing: documents, completeness at Proceed to sign, rendering (spec 0033 #6.4, #6.5, #17.2)."""

import datetime

import pytest

from apps.applications.models import Application, ApplicationDocument

from .factories import (
    client_for,
    codes_of,
    errors_of,
    file_bytes,
    jpeg_upload,
    pdf_upload,
    png_upload,
    schedule_hearing,
    submitted,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)


def new(world, user=None, side="COMPLAINANT", **body):
    user = user or (world.a1 if side == "COMPLAINANT" else world.b1)
    litigant = world.complainant if side == "COMPLAINANT" else world.accused
    body.setdefault("application_type", "GENERIC")
    body.setdefault("raised_by", str(user.pk if user in (world.a1, world.b1) else world.a1.pk))
    body.setdefault("litigant", str(litigant.pk))
    body.setdefault("details", "<p>Reasons.</p>")
    response = client_for(user).post(
        f"/api/v1/cases/{world.case.pk}/applications/", body, format="json"
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def upload(user, application_id, file, **fields):
    return client_for(user).post(
        f"/api/v1/applications/{application_id}/documents/",
        {"file": file, **fields},
        format="multipart",
    )


def set_data(user, application_id, data):
    return client_for(user).patch(
        f"/api/v1/applications/{application_id}/", {"data": data}, format="json"
    )


def proceed(user, application_id):
    return client_for(user).post(f"/api/v1/applications/{application_id}/proceed-to-sign/")


class TestDocuments:
    def test_supporting_document(self, world):
        app_id = new(world, data={"title": "x"})
        response = upload(world.a1, app_id, pdf_upload(), name="Medical certificate")
        assert response.status_code == 201, response.json()
        assert response.json()["is_supporting"] is True
        assert response.json()["name"] == "Medical certificate"

    def test_t21_exe_renamed_pdf_is_refused_and_nothing_stored(self, world):
        app_id = new(world, data={"title": "x"})
        response = upload(world.a1, app_id, pdf_upload("evil.pdf", b"MZ\x90\x00binary"), name="x")
        assert errors_of(response) == [("E13010", "file")]
        assert not ApplicationDocument.objects.exists()

    def test_t22_supporting_document_needs_a_name(self, world):
        app_id = new(world, data={"title": "x"})
        assert errors_of(upload(world.a1, app_id, pdf_upload())) == [("E00002", "name")]

    def test_t23_field_path_the_type_does_not_declare(self, world):
        app_id = new(world, data={"title": "x"})
        response = upload(world.a1, app_id, pdf_upload(), field_path="title")
        assert errors_of(response) == [("E13011", "field_path")]

    def test_t23_data_referencing_another_applications_document(self, world):
        first = new(world, side="ACCUSED", application_type="BAIL")
        second = new(world, side="ACCUSED", application_type="BAIL")
        doc = upload(
            world.b1, first, pdf_upload(), field_path="sureties[0].id_proof_document_ids"
        ).json()
        response = set_data(
            world.b1,
            second,
            {"bail_type": "SURETY", "sureties": [{"id_proof_document_ids": [doc["id"]]}]},
        )
        assert errors_of(response) == [("E13011", "data.sureties[0].id_proof_document_ids")]

    def test_supporting_document_cannot_fill_a_field(self, world):
        app_id = new(world, side="ACCUSED", application_type="BAIL")
        doc = upload(world.b1, app_id, pdf_upload(), name="Other").json()
        response = set_data(
            world.b1,
            app_id,
            {"bail_type": "SURETY", "sureties": [{"id_proof_document_ids": [doc["id"]]}]},
        )
        assert codes_of(response) == ["E13011"]

    def test_field_document_named_by_the_server(self, world):
        app_id = new(world, side="ACCUSED", application_type="BAIL")
        doc = upload(
            world.b1,
            app_id,
            pdf_upload(),
            field_path="data.sureties[0].solvency_document_ids",
            name="ignored",
        ).json()
        assert doc["name"] == "Proof of solvency"
        assert doc["field_path"] == "sureties[0].solvency_document_ids"

    def test_t24_deleting_a_referenced_document(self, world):
        app_id = new(world, side="ACCUSED", application_type="BAIL")
        doc = upload(
            world.b1, app_id, pdf_upload(), field_path="sureties[0].id_proof_document_ids"
        ).json()
        set_data(
            world.b1,
            app_id,
            {"bail_type": "SURETY", "sureties": [{"id_proof_document_ids": [doc["id"]]}]},
        )
        url = f"/api/v1/applications/{app_id}/documents/{doc['id']}/"
        response = client_for(world.b1).delete(url)
        assert response.status_code == 409
        assert codes_of(response) == ["E13012"]
        set_data(world.b1, app_id, {"bail_type": "SURETY", "sureties": [{}]})
        assert client_for(world.b1).delete(url).status_code == 204
        assert not ApplicationDocument.objects.filter(pk=doc["id"]).exists()

    def test_t25_no_documents_after_submission(self, world):
        application = submitted(world)
        response = upload(world.a1, application.pk, pdf_upload(), name="x")
        assert codes_of(response) == ["E13001"]

    def test_t32_production_of_documents_takes_pdf_and_jpeg_only(self, world):
        app_id = new(world, application_type="PRODUCTION_OF_DOCUMENTS")
        path = "documents[0].document_id"
        assert errors_of(upload(world.a1, app_id, png_upload(), field_path=path)) == [
            ("E13010", "file")
        ]
        assert upload(world.a1, app_id, jpeg_upload(), field_path=path).status_code == 201

    def test_png_accepted_as_supporting_document(self, world):
        app_id = new(world, data={"title": "x"})
        assert upload(world.a1, app_id, png_upload(), name="Photo").status_code == 201

    def test_other_side_cannot_attach(self, world):
        app_id = new(world, data={"title": "x"})
        response = upload(world.b1, app_id, pdf_upload(), name="x")
        assert response.status_code == 404

    def test_unknown_document(self, world):
        app_id = new(world, data={"title": "x"})
        response = client_for(world.a1).delete(
            f"/api/v1/applications/{app_id}/documents/00000000-0000-0000-0000-000000000000/"
        )
        assert response.status_code == 404


class TestCompleteness:
    def test_t26_every_gap_on_its_path(self, world):
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {"application_type": "GENERIC"},
            format="json",
        )
        app_id = response.json()["id"]
        response = proceed(world.a1, app_id)
        assert response.status_code == 400
        assert sorted(errors_of(response)) == [
            ("E13007", "details"),
            ("E13008", "data.title"),
            ("E13008", "litigant"),
            ("E13008", "raised_by"),
        ]

    def test_empty_editor_markup_is_no_details(self, world):
        app_id = new(world, details="<p><br></p>", data={"title": "x"})
        assert errors_of(proceed(world.a1, app_id)) == [("E13007", "details")]

    def test_t27_surety_count_mismatch(self, world):
        app_id = new(
            world,
            side="ACCUSED",
            application_type="BAIL",
            data={
                "bail_type": "SURETY",
                "bail_amount": "50000",
                "number_of_sureties": 2,
                "sureties": [{}],
            },
        )
        assert ("E13008", "data.sureties") in errors_of(proceed(world.b1, app_id))

    def test_t28_surety_phone_required_email_not(self, world):
        app_id = new(
            world,
            side="ACCUSED",
            application_type="BAIL",
            data={
                "bail_type": "SURETY",
                "bail_amount": "50000",
                "number_of_sureties": 1,
                "sureties": [{"name": "A", "parent_name": "B", "address": {"city": "Kollam"}}],
            },
        )
        found = errors_of(proceed(world.b1, app_id))
        assert ("E13008", "data.sureties[0].phone") in found
        assert ("E13008", "data.sureties[0].email") not in found

    def test_t29_cash_bail_with_sureties(self, world):
        response = client_for(world.b1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {
                "application_type": "BAIL",
                "data": {"bail_type": "CASH", "sureties": []},
            },
            format="json",
        )
        assert errors_of(response) == [("E13009", "data.sureties")]

    def test_bail_amount_must_be_positive(self, world):
        response = client_for(world.b1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {"application_type": "BAIL", "data": {"bail_type": "CASH", "bail_amount": "-5"}},
            format="json",
        )
        assert errors_of(response) == [("E00001", "data.bail_amount")]

    def test_t141_more_than_ten_sureties_refused(self, world):
        response = client_for(world.b1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {"application_type": "BAIL", "data": {"number_of_sureties": 11}},
            format="json",
        )
        assert errors_of(response) == [("E00001", "data.number_of_sureties")]

    def test_t30_witness_needs_name_or_designation_and_an_address(self, world):
        app_id = new(
            world, application_type="ADDITION_OF_WITNESS", data={"witnesses": [{"age": 30}]}
        )
        found = errors_of(proceed(world.a1, app_id))
        assert ("E13008", "data.witnesses[0].name") in found
        assert ("E13008", "data.witnesses[0].addresses") in found

    def test_witness_mobile_and_pincode_checked_on_save(self, world):
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {
                "application_type": "ADDITION_OF_WITNESS",
                "data": {"witnesses": [{"mobile": "123", "addresses": [{"pincode": "012345"}]}]},
            },
            format="json",
        )
        assert sorted(errors_of(response)) == [
            ("E00001", "data.witnesses[0].addresses[0].pincode"),
            ("E00001", "data.witnesses[0].mobile"),
        ]

    def test_t36_postpone_date_rules(self, world):
        schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        before = (TODAY + datetime.timedelta(days=3)).isoformat()
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {
                "application_type": "POSTPONE_HEARING",
                "data": {"reason_code": "ILLNESS", "proposed_date": before},
            },
            format="json",
        )
        assert errors_of(response) == [("E00001", "data.proposed_date")]
        after = (TODAY + datetime.timedelta(days=12)).isoformat()
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {
                "application_type": "ADVANCE_HEARING",
                "data": {"reason_code": "ILLNESS", "proposed_date": after},
            },
            format="json",
        )
        assert errors_of(response) == [("E00001", "data.proposed_date")]

    def test_reschedule_reason_from_the_list(self, world):
        schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {"application_type": "POSTPONE_HEARING", "data": {"reason_code": "BORED"}},
            format="json",
        )
        assert errors_of(response) == [("E00005", "data.reason_code")]

    def test_warrant_by_hand_needs_an_accused(self, world):
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {
                "application_type": "WARRANT_BY_HAND",
                "data": {"accused_participant_id": str(world.complainant.pk)},
            },
            format="json",
        )
        assert errors_of(response) == [("E00001", "data.accused_participant_id")]
        app_id = new(
            world,
            application_type="WARRANT_BY_HAND",
            data={"accused_participant_id": str(world.accused.pk)},
        )
        assert errors_of(proceed(world.a1, app_id)) == [("E13008", "data.delivery_address")]

    def test_case_transfer_needs_the_requested_court(self, world):
        app_id = new(world, application_type="CASE_TRANSFER")
        assert errors_of(proceed(world.a1, app_id)) == [("E13008", "data.requested_court")]

    @pytest.mark.parametrize(
        ("code", "data"),
        [
            ("GENERIC", {"title": "Adjournment"}),
            ("CASE_SETTLEMENT", {}),
            ("CASE_WITHDRAWAL", {}),
            ("DELAY_CONDONATION", {}),
            ("ABSENT_APPLICATION", {}),
            ("REOPEN_EVIDENCE", {}),
            ("CASE_TRANSFER", {"requested_court": "Kollam"}),
            (
                "ADDITION_OF_WITNESS",
                {"witnesses": [{"name": "W", "addresses": [{"city": "Kollam"}]}]},
            ),
        ],
    )
    def test_t37_complete_payload_goes_to_signature_with_the_default_template(
        self, world, code, data
    ):
        app_id = new(world, application_type=code, data=data)
        response = proceed(world.a1, app_id)
        assert response.status_code == 200, response.json()
        body = response.json()["application"]
        assert body["status"] == "PENDING_SIGNATURE"
        assert body["type"]["template_code"] == "application-default"
        application = Application.objects.get(pk=app_id)
        assert file_bytes(application.signing_file_id).startswith(b"%PDF")

    def test_complete_bail_with_documents(self, world):
        app_id = new(world, side="ACCUSED", application_type="BAIL")
        ids = {}
        for key in ("id_proof_document_ids", "solvency_document_ids"):
            ids[key] = upload(
                world.b1, app_id, pdf_upload(), field_path=f"sureties[0].{key}"
            ).json()["id"]
        response = set_data(
            world.b1,
            app_id,
            {
                "bail_type": "SURETY",
                "bail_amount": "50000.00",
                "number_of_sureties": 1,
                "sureties": [
                    {
                        "name": "S",
                        "parent_name": "P",
                        "phone": "+919876543210",
                        "address": {"line1": "1 Road", "city": "Kollam"},
                        "id_proof_document_ids": [ids["id_proof_document_ids"]],
                        "solvency_document_ids": [ids["solvency_document_ids"]],
                    }
                ],
            },
        )
        assert response.status_code == 200, response.json()
        assert proceed(world.b1, app_id).status_code == 200

    def test_production_of_documents_complete(self, world):
        app_id = new(world, application_type="PRODUCTION_OF_DOCUMENTS")
        doc = upload(world.a1, app_id, pdf_upload(), field_path="documents[0].document_id").json()
        assert proceed(world.a1, app_id).status_code == 400
        set_data(
            world.a1,
            app_id,
            {"documents": [{"document_type": "Bank statement", "document_id": doc["id"]}]},
        )
        assert proceed(world.a1, app_id).status_code == 200

    def test_waiting_on_for_a_clerk(self, world):
        app_id = new(world, user=world.c1, data={"title": "x"})
        body = proceed(world.c1, app_id).json()
        assert body["waiting_on"] == "Adv. Nisha Thomas"

    def test_pdf_render_failure_changes_nothing(self, world):
        from apps.pdf.models import PDFTemplate

        PDFTemplate.objects.filter(key="application-default").update(is_active=False)
        app_id = new(world, data={"title": "x"})
        response = proceed(world.a1, app_id)
        assert response.status_code >= 400
        assert Application.objects.get(pk=app_id).status == "DRAFT"

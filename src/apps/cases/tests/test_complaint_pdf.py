"""The complaint PDF: preview, the copy every signer signs, and back to draft.

efiling.md §16 (the complaint PDF, its signature block DOC-02 and appended
documents DOC-07) and §18 (signing; any edit invalidates every signature).
"""

import base64
import io
from io import StringIO

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from PIL import Image
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from pypdf import PdfReader

from apps.cases.models import (
    Case,
    CaseDocument,
    CaseParticipant,
    CaseStatus,
    ComplaintSigningPackage,
    SigningPackageStatus,
)
from apps.cases.services import complaint_pdf
from apps.cases.services.richtext import to_paragraphs
from apps.cases.services.signing import can_sign_case_filing
from apps.esign.constants import ESignStatus
from apps.esign.models import ESignTransaction
from apps.esign.providers import reset_provider_cache
from apps.files.models import File
from apps.files.services import get_file_content
from apps.files.tests.factories import make_file
from apps.parties.models import Person
from apps.pdf.exceptions import PDFStorageError
from apps.pdf.models import PDFJob, PDFTemplate
from apps.pdf.services.signing import prepare_for_signing
from apps.pdf.tests import test_signing
from apps.pdf.tests.factories import simple_pdf

from .conftest import error_codes
from .test_api import upload
from .test_filing import (
    PIP_AFFIDAVIT,
    POA_MOBILE,
    SECOND_MOBILE,
    make_complete_case,
    submit,
    upload_identity_proof,
)
from .test_participants import MOBILE, PERSON, add, add_poa_holder

pytestmark = pytest.mark.django_db

TEMPLATE_SEED = settings.BASE_DIR.parent / "data" / "seed" / "core" / "pdf"


@pytest.fixture(scope="module")
def signing_esp():
    """A self-signed signer standing in for C-DAC, as the PDF signing tests use."""
    return test_signing.esp.__wrapped__()


@pytest.fixture(autouse=True)
def template():
    """Seed the complaint template, as every environment does."""
    call_command("seed", str(TEMPLATE_SEED), "--strict", stdout=StringIO())


@pytest.fixture
def pdf():
    """Uploads that are real PDFs, so they can be appended to the complaint."""

    def factory(name="scan.pdf", content_type="application/pdf"):
        return SimpleUploadedFile(name, simple_pdf(text=name), content_type=content_type)

    return factory


def png_upload(name="id.png"):
    out = io.BytesIO()
    Image.new("RGB", (600, 900), (20, 120, 200)).save(out, format="PNG")
    return lambda *args, **kwargs: SimpleUploadedFile(name, out.getvalue(), "image/png")


def text_of(content):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


def preview(client, case_id):
    return client.get(reverse("case-complaint-pdf", args=[case_id]))


def prepare(client, case_id):
    return client.post(reverse("case-complaint-pdf", args=[case_id]))


def read(file_id):
    with get_file_content(str(file_id)) as handle:
        return handle.read()


def add_second_complainant(client, case_id, pdf_factory):
    second = add(
        client,
        case_id,
        person={**PERSON, "name": "Anil Rao"},
        mobile_numbers=[SECOND_MOBILE],
        is_party_in_person=True,
        party_in_person_affidavit=PIP_AFFIDAVIT,
    )
    assert second.status_code == 201, second.json()
    upload_identity_proof(client, case_id, pdf_factory, second.json())
    return second.json()


class TestPreview:
    def test_renders_the_complaint_from_the_case(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)

        response = preview(client, draft)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"].startswith("inline;")
        text = text_of(response.content)
        assert "Rajesh Kumar v/s Suresh Patel" in text
        assert "COMPLAINT UNDER SECTION 138 OF THE NEGOTIABLE INSTRUMENTS ACT, 1881" in text
        assert "₹50,000" in text
        assert "15 January 2024" in text
        assert "Funds insufficient" in text
        assert "PREVIEW - NOT FOR FILING" in text
        # Rich text prints as text, never as the editor's markup.
        assert "facts above are true" in text
        assert "<p>" not in text

    def test_laid_out_as_the_prd_sample(self, client, draft, pdf):
        """efiling §16.9 sample: the complaint starts on page 1, no running header or footer."""
        make_complete_case(client, draft, pdf)

        pages = PdfReader(io.BytesIO(preview(client, draft).content)).pages
        first = pages[0].extract_text()

        # The cover heads page 1 and the party details follow on the same page.
        assert "COMPLAINT UNDER SECTION 138" in first and "1. Party details" in first
        assert first.index("COMPLAINT UNDER") < first.index("1. Party details")
        # No "Page x of y" footer and no case reference repeated as a header.
        assert not any("Page 1 of" in page.extract_text() for page in pages)

    def test_stores_nothing(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        files = File.objects.count()

        assert preview(client, draft).status_code == 200

        assert File.objects.count() == files
        assert not PDFJob.objects.exists()

    def test_reflects_the_latest_write(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        preview(client, draft)
        client.put(
            reverse("case-affidavit", args=[draft]),
            {"affidavit": "<p>A corrected affidavit.</p>"},
            format="json",
        )

        assert "A corrected affidavit." in text_of(preview(client, draft).content)

    def test_an_incomplete_case_is_refused_with_what_is_missing(self, client, draft):
        add(client, draft, person=PERSON)

        response = preview(client, draft)

        assert response.status_code == 400
        assert error_codes(response)["participants.accused"] == ["E07005"]

    def test_a_missing_template_is_reported(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        PDFTemplate.objects.filter(key="case-complaint").update(is_active=False)

        response = preview(client, draft)

        assert response.status_code == 404
        assert error_codes(response) == {None: ["E04001"]}

    def test_only_the_filing_side_sees_it(self, client, client_for, other_user, draft, pdf):
        make_complete_case(client, draft, pdf)

        assert preview(client_for(other_user), draft).status_code == 404

    def test_a_case_pending_signature_has_no_preview_mark(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")

        assert "PREVIEW" not in text_of(preview(client, draft).content)


class TestSigningPackage:
    @pytest.fixture
    def pending(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        assert submit(client, draft, "signing").status_code == 200
        return complainant

    def test_a_draft_has_no_copy_to_sign(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)

        response = prepare(client, draft)

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07004"]}

    def test_the_documents_heading_sits_at_the_top_left_in_the_complaint_font(
        self, client, draft, pending
    ):
        body = prepare(client, draft).json()
        complaint_pages = len(PdfReader(io.BytesIO(read(body["complaint_file_id"]))).pages)
        page = PdfReader(io.BytesIO(read(body["signing_file_id"]))).pages[complaint_pages]
        found = []

        def visit(text, cm, tm, font, size):
            if text.strip():
                found.append((cm[4] + tm[4], cm[5] + tm[5], font["/BaseFont"]))

        page.extract_text(visitor_text=visit)

        x, y, font = found[0]
        assert x < 100 and y > 700  # top left, as in the sample
        assert "NotoSans-Bold" in font

    def test_appends_every_uploaded_document_after_the_complaint(self, client, draft, pending):
        response = prepare(client, draft)

        assert response.status_code == 201
        body = response.json()
        signing = read(body["signing_file_id"])
        complaint_pages = len(PdfReader(io.BytesIO(read(body["complaint_file_id"]))).pages)
        uploads = CaseDocument.objects.active().filter(case_id=draft).count()
        # The complaint, the "Documents uploaded" page, then one page per upload.
        assert body["page_count"] == complaint_pages + 1 + uploads
        pages = PdfReader(io.BytesIO(signing)).pages
        assert "Documents uploaded by the Complainant." in pages[complaint_pages].extract_text()
        assert body["current_file_id"] == body["signing_file_id"]
        assert "PREVIEW" not in text_of(signing)

    def test_a_photo_upload_becomes_a_page(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        upload(client, draft, png_upload(), "OTHER_SUPPORTING_DOCUMENT")
        submit(client, draft, "signing")

        response = prepare(client, draft)

        assert response.status_code == 201
        complaint = read(response.json()["complaint_file_id"])
        assert response.json()["page_count"] == len(PdfReader(io.BytesIO(complaint)).pages) + 8
        assert complainant

    def test_a_document_that_cannot_be_appended_is_named(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        heic = SimpleUploadedFile(
            "photo.heic", b"\x00\x00\x00\x18ftypheic" + bytes(64), content_type="image/heic"
        )
        document = upload(client, draft, lambda *a, **k: heic, "OTHER_SUPPORTING_DOCUMENT")
        submit(client, draft, "signing")

        response = prepare(client, draft)

        assert response.status_code == 400
        field = f"documents.{document.json()['case_document_id']}"
        assert error_codes(response) == {field: ["E07036"]}
        assert not ComplaintSigningPackage.objects.exists()

    def test_one_package_per_round(self, client, draft, pending):
        first = prepare(client, draft)
        files = File.objects.count()

        second = prepare(client, draft)

        assert (first.status_code, second.status_code) == (201, 200)
        assert second.json()["signing_file_id"] == first.json()["signing_file_id"]
        assert File.objects.count() == files
        fetched = client.get(reverse("case-complaint-signing", args=[draft]))
        assert fetched.json()["current_file_id"] == first.json()["current_file_id"]

    def test_nothing_to_fetch_before_it_is_prepared(self, client, draft, pending):
        assert client.get(reverse("case-complaint-signing", args=[draft])).status_code == 404

    def test_each_signer_has_a_box_on_the_affidavit_page(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        add_second_complainant(client, draft, pdf)
        submit(client, draft, "signing")

        body = prepare(client, draft).json()

        assert [row["label"] for row in body["signatories"]] == ["Complainant 1", "Complainant 2"]
        boxes = body["signature_placeholders"]
        assert len(boxes) == 2
        assert {box["page"] for box in boxes} == {body["affidavit_page"]}
        # Two to a row (DOC-02): same height, side by side.
        assert boxes[0]["y"] == boxes[1]["y"] and boxes[0]["x"] < boxes[1]["x"]
        signing = read(body["signing_file_id"])
        page = PdfReader(io.BytesIO(signing)).pages[body["affidavit_page"] - 1]
        assert "Rajesh Kumar" in page.extract_text() and "Anil Rao" in page.extract_text()
        for box in boxes:
            keys = ("page", "x", "y", "width", "height", "signer_name", "reason")
            prepare_for_signing(signing, {key: box[key] for key in keys})


class TestSigningPackageContents:
    """Who signs, and the cases the copy to sign cannot be prepared for."""

    @pytest.fixture
    def pending(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        assert submit(client, draft, "signing").status_code == 200
        return complainant

    def test_a_poa_holder_signs_for_their_complainant(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        holder = add_poa_holder(
            client, draft, [complainant["case_participant_id"]], mobile_numbers=[POA_MOBILE]
        )
        assert holder.status_code == 201, holder.json()
        document = upload(
            client,
            draft,
            pdf,
            "POA_DOCUMENT",
            case_participant_id=complainant["case_participant_id"],
        )
        assert document.status_code == 201, document.json()
        assert submit(client, draft, "signing").status_code == 200

        body = prepare(client, draft).json()

        assert [(row["name"], row["label"]) for row in body["signatories"]] == [
            ("Rajesh Kumar", "Complainant 1"),
            ("Suresh Patel", "PoA holder for Complainant 1"),
        ]
        page = PdfReader(io.BytesIO(read(body["signing_file_id"]))).pages[
            body["affidavit_page"] - 1
        ]
        assert "PoA holder for Complainant 1" in page.extract_text()
        # The POA document is listed with whose it is (print §3.2).
        complaint = text_of(read(body["complaint_file_id"]))
        assert "Power of Attorney Authorisation - Complainant 1" in complaint

    def test_the_cover_names_the_other_parties_as_a_count(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        add_second_complainant(client, draft, pdf)

        assert "Rajesh Kumar +1 other v/s Suresh Patel" in text_of(preview(client, draft).content)

    def test_a_missing_template_is_reported(self, client, draft, pending):
        PDFTemplate.objects.filter(key="case-complaint").update(is_active=False)

        response = prepare(client, draft)

        assert response.status_code == 404
        assert error_codes(response) == {None: ["E04001"]}
        assert not ComplaintSigningPackage.objects.exists()

    def test_an_upload_whose_file_is_gone_is_named(self, client, draft, pending):
        document = CaseDocument.objects.filter(case_id=draft).first()
        File.objects.filter(pk=document.document_id).update(is_active=False)

        response = prepare(client, draft)

        assert response.status_code == 400
        assert error_codes(response) == {f"documents.{document.pk}": ["E07036"]}

    def test_an_image_that_cannot_be_read_is_named(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        # A PNG signature with nothing a decoder can read behind it.
        broken = SimpleUploadedFile("scan.png", b"\x89PNG\r\n\x1a\n" + bytes(32), "image/png")
        document = upload(client, draft, lambda *a, **k: broken, "OTHER_SUPPORTING_DOCUMENT")
        assert document.status_code == 201, document.json()
        submit(client, draft, "signing")

        response = prepare(client, draft)

        field = f"documents.{document.json()['case_document_id']}"
        assert error_codes(response) == {field: ["E07036"]}

    def test_a_pdf_upload_that_cannot_be_merged_is_refused(self, client, draft, pdf):
        # Passes the upload check (it starts like a PDF) but is not a parsable PDF.
        make_complete_case(
            client,
            draft,
            lambda *a, **k: SimpleUploadedFile(
                "scan.pdf", b"%PDF-1.4 not really", "application/pdf"
            ),
        )
        submit(client, draft, "signing")

        response = prepare(client, draft)

        assert response.status_code == 400
        assert error_codes(response) == {None: ["E07036"]}
        assert not ComplaintSigningPackage.objects.exists()

    def test_a_copy_over_the_size_limit_is_refused(self, client, draft, pending, settings):
        settings.FILE_MAX_SIZE_BYTES = 1024

        response = prepare(client, draft)

        assert response.status_code == 400
        assert error_codes(response) == {None: ["E07037"]}
        assert not File.objects.filter(tags__name="case-complaint").exists()

    def test_stored_files_are_removed_when_the_package_is_not_saved(
        self, client, draft, pending, monkeypatch
    ):
        def refuse(*args, **kwargs):
            raise PDFStorageError()

        stored = []
        real_store = complaint_pdf.store_document

        def store_then_fail(content, **kwargs):
            if stored:
                refuse()
            stored.append(real_store(content, **kwargs))
            return stored[-1]

        monkeypatch.setattr(complaint_pdf, "store_document", store_then_fail)

        response = prepare(client, draft)

        assert response.status_code == 502
        assert error_codes(response) == {None: ["E04009"]}
        assert not File.objects.filter(pk__in=stored).exists()
        assert not ComplaintSigningPackage.objects.exists()


class TestCaseTitle:
    def test_a_side_with_no_party_prints_a_dash(self):
        assert complaint_pdf._side_title([]) == "-"

    def test_an_institution_is_named_by_its_name_on_the_case(self):
        parties = [
            {"entity_name_at_filing": "Nair Traders", "name_at_filing": None},
            {"entity_name_at_filing": None, "name_at_filing": "Anil Rao"},
            {"entity_name_at_filing": None, "name_at_filing": "Meera Nair"},
        ]

        assert complaint_pdf._side_title(parties) == "Nair Traders +2 others"


class TestCurrentFile:
    """GET complaint-pdf in each stage of signing."""

    def test_pending_signature_before_the_copy_is_prepared_is_rendered(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")

        response = preview(client, draft)

        assert response.status_code == 200
        assert "PREVIEW" not in text_of(response.content)
        assert not ComplaintSigningPackage.objects.exists()

    def test_a_superseded_copy_is_not_shown(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        prepare(client, draft)
        client.post(reverse("case-return-to-draft", args=[draft]), {"reason": "Fix"}, format="json")

        response = preview(client, draft)

        # Back in draft: rendered afresh, as a preview.
        assert response.status_code == 200
        assert "PREVIEW - NOT FOR FILING" in text_of(response.content)

    def test_a_current_file_gone_from_storage_is_reported(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        body = prepare(client, draft).json()
        File.objects.filter(pk=body["current_file_id"]).update(is_active=False)

        response = preview(client, draft)

        assert response.status_code == 404
        assert error_codes(response) == {None: ["E04007"]}

    def test_the_current_file_needs_no_complete_filing(self, client, draft, pdf):
        """What was signed is shown even if a rule added later would call it incomplete."""
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        body = prepare(client, draft).json()
        Case.objects.filter(pk=draft).update(affidavit="")

        response = preview(client, draft)

        assert response.status_code == 200
        assert response.content == read(body["current_file_id"])

    def test_only_the_filing_side_sees_the_signed_file(
        self, client, client_for, other_user, draft, pdf
    ):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        prepare(client, draft)

        assert preview(client_for(other_user), draft).status_code == 404


class TestSignerIds:
    def test_an_anonymous_user_signs_as_no_one(self, draft):
        from django.contrib.auth.models import AnonymousUser

        from apps.cases.services.signing import signer_ids

        assert signer_ids(draft, AnonymousUser()) == set()
        assert signer_ids(draft, None) == set()


class TestSigningPackageModel:
    def test_names_its_round_and_status(self, user, draft):
        case = Case.objects.create(id=draft, case_type="CHEQUE_BOUNCE", created_by=user)
        package = ComplaintSigningPackage(case=case, signing_round=2)

        assert str(package) == f"Signing round 2 of {case.pk} (OPEN)"


class TestCaseFilingAuthorizer:
    """``can_sign_case_filing`` refuses anything that is not the case's awaited signature."""

    @pytest.fixture
    def awaiting(self, client, draft, pdf):
        """A case waiting for the signature of a complainant who has no account."""
        complainant = make_complete_case(client, draft, pdf)
        Person.objects.filter(pk=complainant["person_id"]).update(user=None)
        submit(client, draft, "signing")
        return prepare(client, draft).json()

    def test_a_party_without_an_account_signs_from_their_number(self, make_user, draft, awaiting):
        """efiling §18: the party logs in with the phone number entered for them, then signs."""
        party = make_user()
        party.mobile_number = MOBILE
        party.save(update_fields=["mobile_number"])

        assert can_sign_case_filing(
            user=party,
            entity_type="CASE_FILING",
            entity_id=draft,
            file_id=awaiting["current_file_id"],
        )

    def test_an_account_without_a_mobile_number_matches_no_party(self, make_user, draft, awaiting):
        account = make_user()
        account.mobile_number = ""

        assert not can_sign_case_filing(
            user=account,
            entity_type="CASE_FILING",
            entity_id=draft,
            file_id=awaiting["current_file_id"],
        )

    def test_the_filer_cannot_sign_for_a_party_without_an_account(self, user, draft, awaiting):
        assert not can_sign_case_filing(
            user=user,
            entity_type="CASE_FILING",
            entity_id=draft,
            file_id=awaiting["current_file_id"],
        )

    def test_a_party_with_an_account_signs_only_from_it(self, client, make_user, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        owner = make_user()
        Person.objects.filter(pk=complainant["person_id"]).update(user=owner)
        same_number = make_user()
        submit(client, draft, "signing")
        current = prepare(client, draft).json()["current_file_id"]
        # An account holding the number on the case is not the party's own account.
        owner.mobile_number, same_number.mobile_number = "+919900000001", MOBILE
        owner.save(update_fields=["mobile_number"])
        same_number.save(update_fields=["mobile_number"])

        def allowed(user):
            return can_sign_case_filing(
                user=user, entity_type="CASE_FILING", entity_id=draft, file_id=current
            )

        assert (allowed(owner), allowed(same_number)) == (True, False)

    def test_an_entity_id_that_is_no_case_is_refused(self, user):
        assert (
            can_sign_case_filing(
                user=user, entity_type="CASE_FILING", entity_id="not-a-uuid", file_id="x"
            )
            is False
        )

    def test_no_file_is_refused(self, client, user, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        prepare(client, draft)

        assert (
            can_sign_case_filing(
                user=user, entity_type="CASE_FILING", entity_id=draft, file_id=None
            )
            is False
        )


class TestSigning:
    """Each signer signs the latest signed copy, so every signature is on one file."""

    @pytest.fixture
    def signers(self, client, user, make_user, draft, pdf, settings):
        settings.ESIGN_PROVIDER = "apps.esign.providers.mock.MockESignProvider"
        reset_provider_cache()
        first = make_complete_case(client, draft, pdf)
        second = add_second_complainant(client, draft, pdf)
        second_user = make_user()
        Person.objects.filter(pk=first["person_id"]).update(user=user)
        Person.objects.filter(pk=second["person_id"]).update(user=second_user)
        assert submit(client, draft, "signing").status_code == 200
        package = prepare(client, draft).json()
        boxes = {box["case_participant_id"]: box for box in package["signature_placeholders"]}
        return [
            (user, first, boxes[first["case_participant_id"]]),
            (second_user, second, boxes[second["case_participant_id"]]),
        ]

    @staticmethod
    def initiate(client, case_id, file_id, box):
        keys = ("page", "x", "y", "width", "height", "signer_name", "reason")
        return client.post(
            reverse("esign-initiate"),
            {
                "module": "cases",
                "entity_type": "CASE_FILING",
                "entity_id": str(case_id),
                "file_id": str(file_id),
                "sign_placeholder": {key: box[key] for key in keys},
            },
            format="json",
        )

    @staticmethod
    def complete(client, esp, transaction_id):
        transaction = ESignTransaction.objects.get(pk=transaction_id)
        pkcs7 = test_signing.esp_sign(esp, transaction.document_hash)
        signature = base64.b64encode(pkcs7).decode()
        client.post(
            reverse("esign-callback"),
            {"txn": transaction.provider_transaction_id, "status": "1", "signature": signature},
            format="multipart",
        )
        transaction.refresh_from_db()
        assert transaction.status == ESignStatus.SUCCESS.value, transaction.failure_message
        return transaction

    def current_file(self, client, case_id):
        return client.get(reverse("case-complaint-signing", args=[case_id])).json()[
            "current_file_id"
        ]

    def test_two_signers_sign_one_file(self, client_for, signing_esp, draft, signers):
        esp = signing_esp
        for signer_user, participant, box in signers:
            client = client_for(signer_user)
            started = self.initiate(client, draft, self.current_file(client, draft), box)
            assert started.status_code == 201, started.json()
            transaction = self.complete(client, esp, started.json()["transaction_id"])
            recorded = client.post(
                reverse("case-participant-sign", args=[draft, participant["case_participant_id"]]),
                {"signature_document_id": transaction.signed_file_id},
                format="json",
            )
            assert recorded.status_code == 200, recorded.json()

        package = ComplaintSigningPackage.objects.get(case_id=draft)
        assert package.status == SigningPackageStatus.COMPLETE
        final = read(package.current_file_id)
        embedded = PdfFileReader(io.BytesIO(final)).embedded_signatures
        assert len(embedded) == 2
        for signature in embedded:
            status = validate_pdf_signature(signature, ValidationContext(trust_roots=[esp[1]]))
            assert status.intact and status.valid
        assert submit(client_for(signers[0][0]), draft, "payment").status_code == 200

    def test_the_complaint_pdf_is_always_the_current_signed_file(
        self, client_for, signing_esp, draft, signers
    ):
        """After signing starts, GET complaint-pdf returns the file being signed, signatures in."""
        filer = client_for(signers[0][0])
        package = ComplaintSigningPackage.objects.get(case_id=draft)

        # Prepared, nobody signed yet: the copy to sign, complaint and documents.
        shown = filer.get(reverse("case-complaint-pdf", args=[draft]))
        assert shown.status_code == 200
        assert shown.content == read(package.signing_file_id)

        for count, (signer_user, participant, box) in enumerate(signers, start=1):
            client = client_for(signer_user)
            started = self.initiate(client, draft, self.current_file(client, draft), box)
            transaction = self.complete(client, signing_esp, started.json()["transaction_id"])
            client.post(
                reverse("case-participant-sign", args=[draft, participant["case_participant_id"]]),
                {"signature_document_id": transaction.signed_file_id},
                format="json",
            )

            shown = filer.get(reverse("case-complaint-pdf", args=[draft])).content
            package.refresh_from_db()
            assert str(package.current_file_id) == transaction.signed_file_id
            assert shown == read(package.current_file_id)
            assert len(PdfFileReader(io.BytesIO(shown)).embedded_signatures) == count

        # Still the signed file once the case has moved on to payment.
        assert submit(filer, draft, "payment").status_code == 200
        later = filer.get(reverse("case-complaint-pdf", args=[draft])).content
        assert len(PdfFileReader(io.BytesIO(later)).embedded_signatures) == len(signers)

    def test_only_the_awaited_file_and_signer_may_start(
        self, client_for, make_user, draft, signers
    ):
        signer_user, _, box = signers[0]
        current = ComplaintSigningPackage.objects.get(case_id=draft)

        stranger = self.initiate(client_for(make_user()), draft, current.current_file_id, box)
        wrong_file = self.initiate(client_for(signer_user), draft, current.complaint_file_id, box)

        assert (stranger.status_code, wrong_file.status_code) == (403, 403)
        assert not ESignTransaction.objects.exists()

    def test_one_signer_at_a_time(self, client_for, draft, signers):
        (first_user, _, first_box), (second_user, _, second_box) = signers
        current = ComplaintSigningPackage.objects.get(case_id=draft).current_file_id
        assert self.initiate(client_for(first_user), draft, current, first_box).status_code == 201

        busy = self.initiate(client_for(second_user), draft, current, second_box)

        assert busy.status_code == 403

    def test_a_signature_on_an_older_copy_is_refused(self, client_for, signing_esp, draft, signers):
        esp = signing_esp
        (first_user, first, first_box), (second_user, second, second_box) = signers
        first_client, second_client = client_for(first_user), client_for(second_user)
        stale_source = self.current_file(first_client, draft)
        started = self.initiate(first_client, draft, stale_source, first_box)
        signed = self.complete(first_client, esp, started.json()["transaction_id"])
        first_client.post(
            reverse("case-participant-sign", args=[draft, first["case_participant_id"]]),
            {"signature_document_id": signed.signed_file_id},
            format="json",
        )
        # A second signature made on the copy the first signer already signed.
        stale = ESignTransaction.objects.create(
            module="cases",
            entity_type="CASE_FILING",
            entity_id=str(draft),
            signer=second_user,
            provider="mock",
            source_file_id=stale_source,
            signed_file_id=str(make_file(user=second_user).pk),
            status=ESignStatus.SUCCESS.value,
            completed_at=signed.completed_at,
            expires_at=signed.expires_at,
        )

        response = second_client.post(
            reverse("case-participant-sign", args=[draft, second["case_participant_id"]]),
            {"signature_document_id": stale.signed_file_id},
            format="json",
        )

        assert response.status_code == 400
        assert error_codes(response) == {"signature_document_id": ["E07038"]}


class TestReturnToDraft:
    def back(self, client, case_id, reason="Correcting the cheque amount"):
        return client.post(
            reverse("case-return-to-draft", args=[case_id]), {"reason": reason}, format="json"
        )

    def test_reopens_the_case_and_clears_its_signatures(
        self, client, draft, pdf, django_capture_on_commit_callbacks
    ):
        complainant = make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        package = prepare(client, draft).json()
        CaseParticipant.objects.filter(pk=complainant["case_participant_id"]).update(
            has_signed=True
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = self.back(client, draft)

        assert response.status_code == 200
        assert response.json()["status"] == "DRAFT_IN_PROGRESS"
        case = Case.objects.get(pk=draft)
        assert case.history.first().history_change_reason == "Correcting the cheque amount"
        assert not CaseParticipant.objects.filter(case_id=draft, has_signed=True).exists()
        assert ComplaintSigningPackage.objects.get().status == SigningPackageStatus.SUPERSEDED
        assert not File.objects.filter(
            pk__in=[package["complaint_file_id"], package["signing_file_id"]]
        ).exists()
        # Editable again, then signed in a new round with a new PDF.
        put = client.put(
            reverse("case-affidavit", args=[draft]), {"affidavit": "<p>New.</p>"}, format="json"
        )
        assert put.status_code == 200
        submit(client, draft, "signing")
        assert prepare(client, draft).json()["signing_round"] == 2

    def test_deletes_only_this_rounds_signed_copies(
        self, client, user, draft, pdf, django_capture_on_commit_callbacks
    ):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        body = prepare(client, draft).json()
        signed_copy = make_file(user=user)
        unrelated = make_file(user=user)
        for source, signed in ((body["signing_file_id"], signed_copy), ("elsewhere", unrelated)):
            ESignTransaction.objects.create(
                module="cases",
                entity_type="CASE_FILING",
                entity_id=str(draft),
                signer=user,
                provider="mock",
                source_file_id=source,
                signed_file_id=str(signed.pk),
                status=ESignStatus.SUCCESS.value,
                expires_at=Case.objects.get(pk=draft).updated_at,
            )

        with django_capture_on_commit_callbacks(execute=True):
            assert self.back(client, draft).status_code == 200

        assert not File.objects.filter(pk=signed_copy.pk).exists()
        assert File.objects.filter(pk=unrelated.pk).exists()

    def test_only_a_case_pending_signature(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)

        response = self.back(client, draft)

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07004"]}

    def test_refused_while_a_signature_is_in_progress(self, client, user, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        package = prepare(client, draft).json()
        ESignTransaction.objects.create(
            module="cases",
            entity_type="CASE_FILING",
            entity_id=str(draft),
            signer=user,
            provider="mock",
            source_file_id=package["current_file_id"],
            status=ESignStatus.PENDING.value,
            expires_at=Case.objects.get(pk=draft).updated_at,
        )

        response = self.back(client, draft)

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07039"]}
        assert Case.objects.get(pk=draft).status == CaseStatus.PENDING_SIGN

    def test_a_reason_is_required(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")

        response = client.post(reverse("case-return-to-draft", args=[draft]), {}, format="json")

        assert response.status_code == 400
        assert "reason" in error_codes(response)

    def test_other_users_cases_are_not_found(self, client, client_for, other_user, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")

        assert self.back(client_for(other_user), draft).status_code == 404


class TestRichText:
    def test_keeps_paragraphs_lists_and_emphasis(self):
        html = "<p>I, <b>A &amp; B</b>, state:</p><ol><li>one</li><li><i>two</i></li></ol>"

        assert to_paragraphs(html) == [
            "I, <b>A &amp; B</b>, state:",
            "&nbsp;&nbsp;&nbsp;&nbsp;1. one",
            "&nbsp;&nbsp;&nbsp;&nbsp;2. <i>two</i>",
        ]

    def test_drops_unsafe_markup_and_keeps_its_text(self):
        html = '<p><span style="color:red">x</span><script>alert(1)</script><a href="j">y</a></p>'

        assert to_paragraphs(html) == ["xy"]

    def test_closes_formatting_left_open(self):
        assert to_paragraphs("<p><b>open</p><p>next</p>") == ["<b>open</b>", "next"]

    def test_empty_editor_output_is_nothing(self):
        assert to_paragraphs("<p><br></p>") == []
        assert to_paragraphs(None) == []

    def test_self_closing_line_breaks_are_kept(self):
        assert to_paragraphs("<p>first<br/>second</p>") == ["first<br/>second"]


class TestIsMe:
    """``is_me`` marks the signatories the caller signs as, by the rule e-sign enforces."""

    @pytest.fixture
    def case(self, client, user, make_user, draft, pdf, settings):
        """Two complainants: the filer, and one with no account whose number is on the case."""
        settings.ESIGN_PROVIDER = "apps.esign.providers.mock.MockESignProvider"
        reset_provider_cache()
        first = make_complete_case(client, draft, pdf)
        second = add_second_complainant(client, draft, pdf)
        Person.objects.filter(pk=first["person_id"]).update(user=user)
        assert submit(client, draft, "signing").status_code == 200
        prepare(client, draft)
        party = make_user()
        party.mobile_number = SECOND_MOBILE
        party.save(update_fields=["mobile_number"])
        return {"first": first, "second": second, "party": party}

    @staticmethod
    def mine(client, case_id):
        body = client.get(reverse("case-complaint-signing", args=[case_id])).json()
        return {row["case_participant_id"]: row["is_me"] for row in body["signatories"]}

    def test_each_user_sees_only_the_rows_they_sign_as(
        self, client, client_for, other_user, draft, case
    ):
        first, second = case["first"]["case_participant_id"], case["second"]["case_participant_id"]

        # The filer, by their linked account; the second party, by the number entered for them.
        assert self.mine(client, draft) == {first: True, second: False}
        assert self.mine(client_for(case["party"]), draft) == {first: False, second: True}

    def test_the_prepare_response_carries_it_too(self, client, draft, case):
        body = prepare(client, draft).json()

        assert [row["is_me"] for row in body["signatories"]] == [True, False]

    def test_it_matches_whether_e_sign_lets_the_user_start(self, client_for, user, draft, case):
        """For each signer, true exactly on the rows the e-sign authorizer lets them start."""
        current = ComplaintSigningPackage.objects.get(case_id=draft).current_file_id
        for account in (user, case["party"]):
            rows = self.mine(client_for(account), draft)
            allowed = can_sign_case_filing(
                user=account, entity_type="CASE_FILING", entity_id=draft, file_id=current
            )
            assert any(rows.values()) is allowed is True
            assert list(rows.values()).count(True) == 1

    def test_someone_who_signs_as_no_one_cannot_read_it_or_start(
        self, client_for, make_user, draft, case
    ):
        stranger = make_user()
        package = ComplaintSigningPackage.objects.get(case_id=draft)
        box = next(iter(package.placeholders.values()))

        read = client_for(stranger).get(reverse("case-complaint-signing", args=[draft]))
        started = TestSigning.initiate(
            client_for(stranger),
            draft,
            package.current_file_id,
            {**box, "signer_name": "x", "reason": "y"},
        )

        assert (read.status_code, started.status_code) == (404, 403)

    def test_a_party_without_an_account_can_read_it_from_their_own_device(
        self, client_for, draft, case
    ):
        body = client_for(case["party"]).get(reverse("case-complaint-signing", args=[draft])).json()

        mine = [row for row in body["signatories"] if row["is_me"]]
        assert [row["case_participant_id"] for row in mine] == [
            case["second"]["case_participant_id"]
        ]
        box = next(
            p
            for p in body["signature_placeholders"]
            if p["case_participant_id"] == mine[0]["case_participant_id"]
        )
        started = TestSigning.initiate(
            client_for(case["party"]), draft, body["current_file_id"], box
        )
        assert started.status_code == 201, started.json()

    def test_it_stays_true_after_signing(self, client, user, draft, case):
        first = case["first"]["case_participant_id"]
        CaseParticipant.objects.filter(pk=first).update(has_signed=True)

        body = client.get(reverse("case-complaint-signing", args=[draft])).json()
        row = next(r for r in body["signatories"] if r["case_participant_id"] == first)

        assert (row["has_signed"], row["is_me"]) == (True, True)

    def test_one_person_in_two_roles_is_marked_twice(self, client, user, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        Person.objects.filter(pk=complainant["person_id"]).update(user=user)
        # The holder has no account and their number on the case is the
        # filer's login, so the filer signs as both rows.
        holder = add_poa_holder(
            client, draft, [complainant["case_participant_id"]], mobile_numbers=[POA_MOBILE]
        ).json()
        upload(
            client,
            draft,
            pdf,
            "POA_DOCUMENT",
            case_participant_id=complainant["case_participant_id"],
        )
        Person.objects.filter(pk=holder["person_id"]).update(user=None)
        user.mobile_number = POA_MOBILE
        user.save(update_fields=["mobile_number"])
        submit(client, draft, "signing")

        body = prepare(client, draft).json()

        assert [row["is_me"] for row in body["signatories"]] == [True, True]

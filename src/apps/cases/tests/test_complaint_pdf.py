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
from apps.cases.services.richtext import to_paragraphs
from apps.esign.constants import ESignStatus
from apps.esign.models import ESignTransaction
from apps.esign.providers import reset_provider_cache
from apps.files.models import File
from apps.files.services import get_file_content
from apps.files.tests.factories import make_file
from apps.parties.models import Person
from apps.pdf.models import PDFJob
from apps.pdf.services.signing import prepare_for_signing
from apps.pdf.tests import test_signing
from apps.pdf.tests.factories import simple_pdf

from .conftest import error_codes
from .test_api import upload
from .test_filing import (
    PIP_AFFIDAVIT,
    SECOND_MOBILE,
    make_complete_case,
    submit,
    upload_identity_proof,
)
from .test_participants import PERSON, add

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
        assert "Complaint under Section 138 of the Negotiable Instruments Act, 1881" in text
        assert "₹50,000" in text
        assert "15 January 2024" in text
        assert "Funds insufficient" in text
        assert "PREVIEW - NOT FOR FILING" in text
        # Rich text prints as text, never as the editor's markup.
        assert "facts above are true" in text
        assert "<p>" not in text

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

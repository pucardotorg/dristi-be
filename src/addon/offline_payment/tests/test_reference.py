"""The payment request reference (spec 0032 #5.2, #17.1 REF-01 – REF-12)."""

import re
import uuid
from datetime import UTC, datetime

import pytest

from addon.offline_payment import reference
from addon.offline_payment.reference import ALPHABET, CHECK_ALPHABET, MalformedReference

from .base import ISSUED_AT, REFERENCE_UUID

FORMAT = re.compile(
    r"^[A-Z]{2,4}-\d{6}-[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z*~$=U]$"
)
PREFIX = "OFL"


def ref(uid=REFERENCE_UUID, at=ISSUED_AT, prefix=PREFIX):
    return reference.build(uid, at, prefix)


def rejected(value, prefix=PREFIX) -> bool:
    try:
        reference.parse(value, prefix)
    except MalformedReference:
        return True
    return False


# Positions of the date and body characters in "OFL-YYMMDD-AAAAA-BBBBB-C".
DATE_POSITIONS = list(range(4, 10))
BODY_POSITIONS = [*range(11, 16), *range(17, 22)]
CHECK_POSITION = 23


def test_ref_01_deterministic():
    assert ref() == ref()


def test_ref_02_different_uuids_differ():
    assert ref(uuid.uuid4()) != ref(uuid.uuid4())


def test_ref_03_format():
    for _ in range(200):
        value = ref(uuid.uuid4())
        assert FORMAT.match(value), value
        assert reference.normalise(value, PREFIX) == value


def test_ref_04_date_is_the_ist_date():
    assert ref(at=datetime(2026, 11, 11, 18, 29, 59, tzinfo=UTC)).split("-")[1] == "261111"
    assert ref(at=datetime(2026, 11, 11, 18, 30, 0, tzinfo=UTC)).split("-")[1] == "261112"


def test_ref_05_custom_prefix():
    value = ref(prefix="CRT")
    assert value.startswith("CRT-")
    assert reference.normalise(value, "CRT") == value
    assert rejected(value, PREFIX)


def test_ref_06_normalise_case_spaces_and_dashes():
    canonical = ref()
    compact = canonical.replace("-", "")
    for variant in (canonical.lower(), compact, compact.lower(), " ".join(canonical.split("-"))):
        assert reference.normalise(variant, PREFIX) == canonical


def test_ref_07_lookalikes_in_the_body_only():
    # A body made of 1s and 0s, so its I/L/O spellings can be typed.
    uid = uuid.UUID(int=0)
    canonical = ref(uid)
    typed = canonical.replace("-00000-00000-", "-OOOOO-0O0O0-")
    assert reference.normalise(typed, PREFIX) == canonical

    ones = uuid.UUID(int=int("00001" * 10, 2))  # every body symbol is "1"
    canonical = ref(ones)
    assert "-11111-11111-" in canonical
    assert reference.normalise(canonical.replace("11111-11111", "IiLlI-lLiI1"), PREFIX) == (
        canonical
    )
    # The prefix is matched as configured: "0FL" is not "OFL".
    assert rejected("0" + canonical[1:])


def _substitutes(value, position):
    alphabet = (
        CHECK_ALPHABET
        if position == CHECK_POSITION
        else ("0123456789" if position in DATE_POSITIONS else ALPHABET)
    )
    for symbol in alphabet:
        if symbol != value[position]:
            yield value[:position] + symbol + value[position + 1 :]


@pytest.mark.parametrize("uid", [REFERENCE_UUID, uuid.UUID(int=0), uuid.UUID(int=2**128 - 1)])
def test_ref_08_every_single_substitution_is_rejected(uid):
    value = ref(uid)
    for position in [*DATE_POSITIONS, *BODY_POSITIONS, CHECK_POSITION]:
        for typo in _substitutes(value, position):
            assert rejected(typo), typo


@pytest.mark.parametrize("uid", [REFERENCE_UUID, uuid.uuid4(), uuid.uuid4()])
def test_ref_09_every_adjacent_transposition_is_rejected(uid):
    value = ref(uid)
    compact = value.replace("-", "")
    pairs = [(i, i + 1) for i in range(3, 3 + 5)]  # within the date
    pairs += [(i, i + 1) for i in range(9, 9 + 9)]  # within the body, across its dash too
    for left, right in pairs:
        if compact[left] == compact[right]:
            continue
        swapped = compact[:left] + compact[right] + compact[left] + compact[right + 1 :]
        assert rejected(swapped), (value, left)


@pytest.mark.parametrize(
    "value",
    [
        "XYZ-261111-7K3QF-9XM2H-V",  # wrong prefix
        "OFL-261111-7K3QF-9XM2H",  # too short
        "OFL-261111-7K3QF-9XM2H-VV",  # too long
        "OFL-261341-7K3QF-9XM2H-V",  # impossible date
        "OFL-261111-7K3QU-9XM2H-V",  # U is not a body symbol
        "OFL-26111A-7K3QF-9XM2H-V",  # letter in the date
        "OFL-261111-7K3QF-9XM2H-#",  # not a check symbol
    ],
)
def test_ref_10_malformed(value):
    assert rejected(value)


@pytest.mark.parametrize("value", ["", None, "O" * 200, "OFL-٢٦١١١١-7K3QF-9XM2H-V", 12345, b"OFL"])
def test_ref_11_junk_raises_only_the_parse_error(value):
    assert rejected(value)


def test_ref_12_an_egras_application_number_is_not_ours():
    assert rejected("DR0F9D3A2B1C")
    assert rejected("DR-0F9D3A2B1C4E5F6A")


def test_parse_returns_the_issue_date():
    parsed = reference.parse(ref(), PREFIX)
    assert parsed.issued_on == ISSUED_AT.date()
    assert parsed.body == REFERENCE_UUID.int & reference.BODY_MASK


def test_build_refuses_a_naive_time():
    with pytest.raises(ValueError):
        reference.build(REFERENCE_UUID, datetime(2026, 11, 11, 9), PREFIX)

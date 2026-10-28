"""e-GRAS wire constants, status vocabulary and internal failure codes.

Everything here is e-GRAS specific. The failure codes are *internal* (spec 0022
#10): they ride on ``ProviderError.code`` / ``ProviderStatus.failure_code`` and
are stored on ``Payment.failure_code``, but ``apps.payments`` maps the exception
*class* to its own registered API code. No e-GRAS code ever reaches a client.
"""

import re
from zoneinfo import ZoneInfo

PROVIDER_NAME = "egras"
PROVIDER_PATH = "addon.egras_payment_gateway.provider.EGRASPaymentProvider"

# e-GRAS carries whole rupees on IST timestamps with no timezone suffix.
IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Initiation form fields (spec 0022 #4.2)
# ---------------------------------------------------------------------------
FIELD_DTO = "DTO"
FIELD_STO = "STO"
FIELD_DDO = "DDO"
FIELD_DEPT_CODE = "Deptcode"
FIELD_OFFICE_NAME = "Officename"
FIELD_USER_ID = "USERID"
FIELD_CHALLAN_YEAR = "ChallanYear"
FIELD_APPLICATION_NUMBER = "Applicationnumber"
FIELD_FULLNAME = "Fullname"
FIELD_CITYNAME = "Cityname"
FIELD_ADDRESS = "Address"
FIELD_PINCODE = "PINCODE"
FIELD_SECURITY_EMAIL = "Securityemail"
FIELD_SECURITY_PHONE = "Securityphone"
FIELD_BANK = "bank"
FIELD_PTYPE = "ptype"
FIELD_REMARKS = "Remarks"
FIELD_TOTAL_AMOUNT = "TotalAmount"
FIELD_SCHEME_COUNT = "SCHEMECOUNT"
FIELD_UURL = "UURL"

# Only net banking / UPI is in scope (spec 0022 #4.1); manual challans (``M``)
# are out of scope.
PTYPE_NET_BANKING = "N"

# Scheme field naming, from the NIC v3.6 sample request (page 12): the first
# head posts as ``SCHEMENAME`` (no suffix) with ``FEEAMOUNT1``. The field-list
# notes say ``SCHEMENAME1``; the working sample is authoritative, so the first
# scheme name carries no suffix. The multi-scheme suffix pattern
# (``SCHEMENAME2…`` vs ``SCHEMENAME1…``) has no sample and must be confirmed
# with NIC — the first iteration is single-scheme (SCHEMECOUNT=1).
SCHEME_NAME_FIELD = "SCHEMENAME"
FEE_AMOUNT_FIELD = "FEEAMOUNT"
FIRST_SCHEME_INDEX = 1


def scheme_name_field(index: int) -> str:
    """Form field name for the ``index``-th scheme (1-based).

    The first head is ``SCHEMENAME`` (no suffix), per the NIC sample; later
    heads are ``SCHEMENAME2``, ``SCHEMENAME3``, …
    """

    if index == FIRST_SCHEME_INDEX:
        return SCHEME_NAME_FIELD
    return f"{SCHEME_NAME_FIELD}{index}"


def fee_amount_field(index: int) -> str:
    """Form field name for the ``index``-th fee amount (1-based): ``FEEAMOUNT1`` …"""

    return f"{FEE_AMOUNT_FIELD}{index}"


# A head of account is a 17-character government scheme code, ``NNNN-NN-NNN-NN-NN``.
SCHEME_CODE_RE = re.compile(r"^\d{4}-\d{2}-\d{3}-\d{2}-\d{2}$")

# ``Applicationnumber`` is at most 20 characters (spec 0022 #4.2, #4.4).
MAX_APPLICATION_NUMBER = 20

# ---------------------------------------------------------------------------
# Callback / verification field names (spec 0022 #5.1, #6.2)
# ---------------------------------------------------------------------------
CALLBACK_APPLICATION_NUMBER = "applicationnumber"
CALLBACK_GRN = "grn"
CALLBACK_STATUS = "status"
CALLBACK_CIN = "cin"
CALLBACK_BANKCODE = "bankcode"
CALLBACK_AMOUNT = "amount"
CALLBACK_TDATE = "tdate"
CALLBACK_PAYMENT_TYPE = "payment_type"

# SOAP GRN status service (spec 0022 #6.1). The operation looks a transaction
# up by *our own* identity — never by a callback-supplied GRN. These values are
# taken from the live WSDL (grn_status.asmx?WSDL): a .NET ASMX service in the
# default ``http://tempuri.org/`` namespace, whose GetGrnDetails_identity takes
# parameters named ``identity`` (our Applicationnumber) and ``dept`` (our
# Deptcode) and returns an ArrayOfGrnDetails.
SOAP_OPERATION = "GetGrnDetails_identity"
SOAP_NAMESPACE = "http://tempuri.org/"
SOAP_ACTION = f"{SOAP_NAMESPACE}{SOAP_OPERATION}"
SOAP_PARAM_APPLICATION = "identity"
SOAP_PARAM_DEPT_CODE = "dept"
SOAP_CONTENT_TYPE = "text/xml; charset=utf-8"

# ``GrnDetails`` elements in the SOAP verification response (inside the
# ArrayOfGrnDetails the identity lookup returns).
GRN_DETAILS_ELEMENT = "GrnDetails"
GRN_ELEMENT = "GRN"
AMOUNT_ELEMENT = "Amount"
PURPOSE_ELEMENT = "Purpose"
STATUS_ELEMENT = "Status"
CIN_ELEMENT = "CIN"
BANKDATE_ELEMENT = "Bankdate"

# ---------------------------------------------------------------------------
# e-GRAS status vocabulary (spec 0022 #6.3), matched case-insensitively.
# ---------------------------------------------------------------------------
STATUS_SUCCESS = {"successfull", "success"}
STATUS_FAILURE = "failure"
STATUS_PENDING = "pending"
STATUS_NOT_FOUND = "not found"

# ---------------------------------------------------------------------------
# Internal failure codes (spec 0022 #10)
# ---------------------------------------------------------------------------
EGRAS_DISABLED = "EGRAS_DISABLED"
EGRAS_INVALID_CONFIGURATION = "EGRAS_INVALID_CONFIGURATION"
EGRAS_UNSUPPORTED_CURRENCY = "EGRAS_UNSUPPORTED_CURRENCY"
EGRAS_SCHEME_UNMAPPED = "EGRAS_SCHEME_UNMAPPED"
EGRAS_FRACTIONAL_AMOUNT = "EGRAS_FRACTIONAL_AMOUNT"
EGRAS_TOO_MANY_SCHEMES = "EGRAS_TOO_MANY_SCHEMES"
EGRAS_AMOUNT_INCONSISTENT = "EGRAS_AMOUNT_INCONSISTENT"
EGRAS_INVALID_PAYER = "EGRAS_INVALID_PAYER"
EGRAS_INVALID_BANK = "EGRAS_INVALID_BANK"
EGRAS_BANK_REQUIRED = "EGRAS_BANK_REQUIRED"
EGRAS_CALLBACK_MALFORMED = "EGRAS_CALLBACK_MALFORMED"
EGRAS_VERIFY_TIMEOUT = "EGRAS_VERIFY_TIMEOUT"
EGRAS_VERIFY_UNAVAILABLE = "EGRAS_VERIFY_UNAVAILABLE"
EGRAS_VERIFY_MALFORMED = "EGRAS_VERIFY_MALFORMED"
EGRAS_VERIFY_EMPTY = "EGRAS_VERIFY_EMPTY"
EGRAS_PAYMENT_FAILED = "EGRAS_PAYMENT_FAILED"
EGRAS_SUCCESS_INCOMPLETE = "EGRAS_SUCCESS_INCOMPLETE"
EGRAS_UNKNOWN_STATUS = "EGRAS_UNKNOWN_STATUS"

# Safe, user-presentable message kept on ``ProviderStatus.failure_message``; the
# raw e-GRAS ``Status`` text only ever goes to the log line (spec 0022 #10).
FAILURE_MESSAGE = "The payment could not be completed at e-GRAS."

# ---------------------------------------------------------------------------
# Structured log events (spec 0022 #12)
# ---------------------------------------------------------------------------
LOGGER_NAME = "addon.egras_payment_gateway"
EVENT_REQUEST_BUILT = "EGRAS_REQUEST_BUILT"
EVENT_CALLBACK_RECEIVED = "EGRAS_CALLBACK_RECEIVED"
EVENT_VERIFY_REQUEST = "EGRAS_VERIFY_REQUEST"
EVENT_VERIFY_RESPONSE = "EGRAS_VERIFY_RESPONSE"
# More than one successful GRN for one Applicationnumber (e.g. a double payment):
# credited once, flagged for reconciliation by apps.payments.
EVENT_MULTIPLE_SUCCESS = "EGRAS_MULTIPLE_SUCCESS"

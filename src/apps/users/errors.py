"""Error codes for registration and login (domain 01, spec 0000 section 9)."""

from apps.api.errors import define

OTP_INVALID = define("E01001", "Invalid or expired code.", status=401)
ACCOUNT_ALREADY_REGISTERED = define(
    "E01002", "Account already registered with this mobile number.", status=409
)
INVALID_CREDENTIALS = define("E01003", "Invalid credentials.", status=401)
REGISTRATION_ALREADY_COMPLETE = define("E01004", "Registration is already complete.", status=409)
OTP_RESEND_TOO_SOON = define("E01005", "A code was already sent to this number.", status=429)
REGISTRATION_INCOMPLETE = define("E01006", "Registration is not complete.", status=403)
TERMS_NOT_CURRENT = define("E01007", "The current terms have not been accepted.", status=403)
CREDENTIAL_CHOICE = define("E01008", "Provide exactly one of otp or password.")
EMAIL_TAKEN = define("E01009", "An account with this email already exists.")
TERMS_NOT_ACCEPTED = define("E01010", "The terms must be accepted to register.")
PASSWORD_REJECTED = define("E01011", "The password does not meet the password policy.")

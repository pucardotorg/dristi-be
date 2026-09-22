"""HTTP transport for the CDAC gateway: form build, TLS, timeout, POST."""

import logging
import ssl

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.ssl_ import create_urllib3_context

from apps.messaging.services import MessageSendError

from . import constants

logger = logging.getLogger(constants.LOGGER_NAME)

# Fixed properties of the CDAC contract, not configuration.
CONTENT_TYPE = "application/x-www-form-urlencoded"
_REDACTED_FIELDS = ("password", "key")


class TLSv12Adapter(HTTPAdapter):
    """Transport adapter that refuses anything below TLS 1.2."""

    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = context
        return super().proxy_manager_for(*args, **kwargs)


def mask_form(form: dict) -> dict:
    """Return a loggable copy of the form: secrets dropped, recipient masked."""

    masked = {key: value for key, value in form.items() if key not in _REDACTED_FIELDS}
    number = masked.get("mobileno", "")
    if number:
        masked["mobileno"] = f"{number[:4]}{'*' * max(len(number) - 8, 0)}{number[-4:]}"
    masked.pop("content", None)
    return masked


class CDACClient:
    """Posts a prepared form to the gateway and returns the raw outcome."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.mount("https://", TLSv12Adapter())

    def post(self, form: dict, log_context: dict | None = None) -> tuple[int, str]:
        """POST the form and return ``(status_code, body)``.

        Makes no judgement about success; see :mod:`response`.
        """

        context = log_context or {}
        if not self.cfg.verify_ssl:
            urllib3.disable_warnings(InsecureRequestWarning)

        logger.info(
            "event=%s message_id=%s correlation_id=%s gateway=%s url=%s "
            "service_type=%s prefix_applied=%s body=%s",
            constants.EVENT_GATEWAY_REQUEST,
            context.get("message_id", ""),
            context.get("correlation_id", ""),
            constants.PROVIDER_NAME,
            self.cfg.url,
            form.get("smsservicetype", ""),
            bool(self.cfg.mobile_prefix),
            mask_form(form),
        )

        try:
            response = self.session.post(
                self.cfg.url,
                data=form,
                headers={"Content-Type": CONTENT_TYPE},
                timeout=self.cfg.timeout,
                verify=self.cfg.verify_ssl,
            )
        except requests.Timeout as exc:
            raise MessageSendError(
                f"CDAC gateway timed out: {exc}", code=constants.GATEWAY_TIMEOUT
            ) from exc
        except requests.ConnectionError as exc:
            raise MessageSendError(
                f"CDAC gateway connection failed: {exc}",
                code=constants.GATEWAY_CONNECTION_ERROR,
            ) from exc
        except requests.RequestException as exc:
            raise MessageSendError(
                f"CDAC gateway unavailable: {exc}", code=constants.GATEWAY_UNAVAILABLE
            ) from exc

        return response.status_code, response.text or ""

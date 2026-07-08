"""Shared detection + HTTP shaping for missing/expired AWS credentials.

maki reads LIVE AWS as the operator's assumed (SSO) identity. When those creds are absent or
expired, boto3 raises a ``NoCredentialsError`` (none configured) or a ``ClientError`` whose
error code is ``ExpiredToken`` / ``ExpiredTokenException`` / ``UnauthorizedException`` (assumed
session lapsed). Left uncaught those surface as an opaque ``500`` that looks like a maki bug.

``is_credentials_error`` classifies them; the registered exception handler turns them into a
distinguishable ``503`` with a typed ``{"error": "aws_credentials_unavailable", ...}`` body so the
SPA can render a "re-run assume" panel instead of a generic failure.
"""

import logging

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    CredentialRetrievalError,
    NoCredentialsError,
    TokenRetrievalError,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Stable typed code the frontend keys off. Keep in sync with frontend/src/api.ts.
CREDENTIALS_UNAVAILABLE = "aws_credentials_unavailable"

# ClientError error codes that mean "creds present but no longer valid". STS expiry surfaces as
# ExpiredToken/ExpiredTokenException; AccessDenied is deliberately NOT here — a durable IAM
# authorization gap must surface as a real error, not a misleading "re-run assume" 503.
_EXPIRED_CODES = frozenset(
    {
        "ExpiredToken",
        "ExpiredTokenException",
        "UnauthorizedException",
        "InvalidClientTokenId",
        "RequestExpired",
    }
)

# botocore-level errors that mean "no usable creds were found at all".
_NO_CREDS_ERRORS = (NoCredentialsError, TokenRetrievalError, CredentialRetrievalError)


def is_credentials_error(exc: BaseException) -> bool:
    """True when ``exc`` is a missing/expired-credentials failure rather than a real bug."""
    if isinstance(exc, _NO_CREDS_ERRORS):
        return True
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code") in _EXPIRED_CODES
    return False


def credentials_unavailable_response() -> JSONResponse:
    """The canonical 503 body for a missing/expired-credentials failure."""
    return JSONResponse(
        status_code=503,
        content={
            "error": CREDENTIALS_UNAVAILABLE,
            "detail": (
                "AWS credentials are missing or expired. Re-run `assume` in the shell that "
                "started the backend, then restart uvicorn in that same shell."
            ),
        },
    )


async def _aws_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Turn a creds failure into a typed 503; re-raise anything else as a real error.

    Registered for ``BotoCoreError`` and ``ClientError``. Only credentials failures get the
    friendly 503 — any other AWS error is a genuine fault and is re-raised so FastAPI's default
    500 handling (and the logs) treat it as such.
    """
    if is_credentials_error(exc):
        logger.warning("AWS credentials unavailable: %s", type(exc).__name__)
        return credentials_unavailable_response()
    raise exc


def register_aws_error_handlers(app: FastAPI) -> None:
    """Wire the creds-aware handler onto the FastAPI app for boto3's error types."""
    app.add_exception_handler(BotoCoreError, _aws_error_handler)
    app.add_exception_handler(ClientError, _aws_error_handler)

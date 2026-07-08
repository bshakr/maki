from unittest.mock import patch

from botocore.exceptions import ClientError, NoCredentialsError
from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import IdentityResponse


def test_get_identity_returns_caller_identity():
    fake = IdentityResponse(
        account="123456789012",
        arn="arn:aws:sts::123456789012:assumed-role/AdminRole/bob.smith",
        user_id="AROAEXAMPLE:bob.smith",
        name="bob.smith",
        region="eu-west-1",
    )
    with patch("maki.identity.routes.get_identity_service") as factory:
        factory.return_value.get_identity.return_value = fake
        client = TestClient(app)
        r = client.get("/api/identity")
    assert r.status_code == 200
    body = r.json()
    assert body["account"] == "123456789012"
    assert body["name"] == "bob.smith"


def test_no_credentials_returns_typed_503():
    with patch("maki.identity.routes.get_identity_service") as factory:
        factory.return_value.get_identity.side_effect = NoCredentialsError()
        client = TestClient(app)
        r = client.get("/api/identity")
    assert r.status_code == 503
    assert r.json()["error"] == "aws_credentials_unavailable"


def test_expired_token_client_error_returns_typed_503():
    err = ClientError(
        {"Error": {"Code": "ExpiredToken", "Message": "token expired"}}, "GetCallerIdentity"
    )
    with patch("maki.identity.routes.get_identity_service") as factory:
        factory.return_value.get_identity.side_effect = err
        client = TestClient(app)
        r = client.get("/api/identity")
    assert r.status_code == 503
    assert r.json()["error"] == "aws_credentials_unavailable"


def test_non_creds_client_error_is_not_masked_as_503():
    # A genuine AWS fault (not a creds problem) must NOT be turned into the friendly 503.
    err = ClientError(
        {"Error": {"Code": "ServiceUnavailable", "Message": "boom"}}, "GetCallerIdentity"
    )
    with patch("maki.identity.routes.get_identity_service") as factory:
        factory.return_value.get_identity.side_effect = err
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/identity")
    assert r.status_code == 500

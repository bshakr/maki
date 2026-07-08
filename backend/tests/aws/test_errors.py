from botocore.exceptions import (
    ClientError,
    CredentialRetrievalError,
    NoCredentialsError,
    TokenRetrievalError,
)

from maki.aws.errors import is_credentials_error


def test_no_credentials_error_is_creds_error():
    assert is_credentials_error(NoCredentialsError()) is True


def test_token_retrieval_error_is_creds_error():
    assert is_credentials_error(TokenRetrievalError(provider="sso", error_msg="x")) is True


def test_credential_retrieval_error_is_creds_error():
    assert is_credentials_error(CredentialRetrievalError(provider="sso", error_msg="x")) is True


def test_expired_token_client_error_is_creds_error():
    err = ClientError({"Error": {"Code": "ExpiredToken", "Message": "m"}}, "Op")
    assert is_credentials_error(err) is True


def test_unauthorized_client_error_is_creds_error():
    err = ClientError({"Error": {"Code": "UnauthorizedException", "Message": "m"}}, "Op")
    assert is_credentials_error(err) is True


def test_unrelated_client_error_is_not_creds_error():
    err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "m"}}, "Op")
    assert is_credentials_error(err) is False


def test_access_denied_is_not_creds_error():
    # A durable IAM authorization gap must NOT masquerade as expired creds, or the user is told
    # to re-run `assume` when the real fix is an IAM policy change. STS expiry is ExpiredToken.
    err = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "m"}}, "Op")
    assert is_credentials_error(err) is False


def test_plain_exception_is_not_creds_error():
    assert is_credentials_error(ValueError("nope")) is False

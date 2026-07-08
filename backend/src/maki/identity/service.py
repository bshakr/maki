from maki.schemas import IdentityResponse


class IdentityService:
    """The assumed AWS identity behind the backend, via ``sts:GetCallerIdentity``.

    A creds failure propagates out of ``get_caller_identity`` as a botocore error and is shaped
    into a typed 503 by the shared AWS error handler — this service does not swallow it.
    """

    def __init__(self, client, region: str | None = None):
        self._client = client
        self._region = region

    def get_identity(self) -> IdentityResponse:
        resp = self._client.get_caller_identity()
        arn = resp.get("Arn")
        return IdentityResponse(
            account=resp.get("Account"),
            arn=arn,
            user_id=resp.get("UserId"),
            name=friendly_name(arn),
            region=self._region,
        )


def friendly_name(arn: str | None) -> str | None:
    """Parse a human-friendly name out of an STS caller ARN.

    Assumed-role ARNs look like
    ``arn:aws:sts::123456789012:assumed-role/<role-name>/<session-name>`` — the session name is
    the most operator-meaningful part (it's usually the person's SSO login), so prefer it and fall
    back to the role name. IAM-user ARNs (``.../user/<name>``) yield the user name.
    """
    if not arn:
        return None
    resource = arn.split(":", 5)[-1]
    parts = [p for p in resource.split("/") if p]
    if not parts:
        return None
    # assumed-role/<role>/<session> → session name (usually the SSO login).
    # user/<name>, federated-user/<name>, or a bare resource → the trailing segment.
    return parts[-1]

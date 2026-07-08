from unittest.mock import MagicMock

from maki.identity.service import IdentityService, friendly_name


def test_friendly_name_prefers_session_from_assumed_role():
    arn = "arn:aws:sts::123456789012:assumed-role/AdminRole/bob.smith"
    assert friendly_name(arn) == "bob.smith"


def test_friendly_name_from_iam_user():
    assert friendly_name("arn:aws:iam::123456789012:user/deploy-bot") == "deploy-bot"


def test_friendly_name_none_for_missing_arn():
    assert friendly_name(None) is None
    assert friendly_name("") is None


def test_get_identity_maps_caller_identity():
    client = MagicMock()
    client.get_caller_identity.return_value = {
        "Account": "123456789012",
        "Arn": "arn:aws:sts::123456789012:assumed-role/AdminRole/bob.smith",
        "UserId": "AROAEXAMPLE:bob.smith",
    }
    out = IdentityService(client, region="eu-west-1").get_identity()
    assert out.account == "123456789012"
    assert out.name == "bob.smith"
    assert out.user_id == "AROAEXAMPLE:bob.smith"
    assert out.region == "eu-west-1"

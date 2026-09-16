from unittest.mock import MagicMock

import httpx

from maki.cli import main


def _client(status_code=200, payload=None):
    client = MagicMock()
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload if payload is not None else {}
    client.get.return_value = response
    client.post.return_value = response
    client.delete.return_value = response
    return client


def test_watch_posts_the_service():
    client = _client(status_code=201, payload={"service": "insights"})
    assert main(["watch", "insights"], client=client) == 0
    assert client.post.call_args.kwargs["json"] == {"service": "insights"}


def test_unwatch_deletes_the_service():
    client = _client(status_code=204)
    assert main(["unwatch", "insights"], client=client) == 0
    assert "/api/watches/insights" in client.delete.call_args.args[0]


def test_watches_lists(capsys):
    client = _client(payload={"watches": [{"service": "insights", "created_at": "2026-09-16Z"}]})
    assert main(["watches"], client=client) == 0
    assert "insights" in capsys.readouterr().out


def test_watches_hints_when_empty(capsys):
    client = _client(payload={"watches": []})
    assert main(["watches"], client=client) == 0
    assert "maki watch" in capsys.readouterr().out


def test_unknown_service_reports_the_api_detail(capsys):
    client = _client(status_code=404, payload={"detail": "unknown service 'nope'"})
    assert main(["watch", "nope"], client=client) == 1
    assert "unknown service 'nope'" in capsys.readouterr().err


def test_non_json_error_body_still_reports_the_status(capsys):
    client = _client(status_code=502)
    client.get.return_value.json.side_effect = ValueError("not json")
    assert main(["watches"], client=client) == 1
    assert "502" in capsys.readouterr().err


def test_html_body_on_a_200_is_not_a_maki_response(capsys):
    client = _client()
    client.get.return_value.json.side_effect = ValueError("not json")
    assert main(["watches"], client=client) == 1
    assert "not a maki API response" in capsys.readouterr().err


def test_json_list_body_on_a_200_is_not_a_maki_response(capsys):
    client = _client(payload=[{"service": "insights"}])
    assert main(["watches"], client=client) == 1
    assert "not a maki API response" in capsys.readouterr().err


def test_connection_refused_is_a_friendly_message(capsys):
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError("refused")
    assert main(["watches"], client=client) == 2
    assert "backend running" in capsys.readouterr().err


def test_connect_timeout_is_a_friendly_message(capsys):
    client = MagicMock()
    client.get.side_effect = httpx.ConnectTimeout("")
    assert main(["watches"], client=client) == 2
    err = capsys.readouterr().err
    assert "backend running" in err
    assert "ConnectTimeout" in err


def test_base_url_without_a_scheme_is_a_friendly_message(capsys):
    client = MagicMock()
    client.get.side_effect = httpx.UnsupportedProtocol("Request URL is missing an 'http://'")
    assert main(["watches"], client=client) == 2
    assert "missing an 'http://'" in capsys.readouterr().err


def test_base_url_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("MAKI_BASE_URL", raising=False)
    client = _client(payload={"watches": []})
    main(["watches"], client=client)
    assert client.get.call_args.args[0] == "http://127.0.0.1:8787/api/watches"


def test_base_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAKI_BASE_URL", "http://localhost:8788/")
    client = _client(payload={"watches": []})
    main(["watches"], client=client)
    assert client.get.call_args.args[0] == "http://localhost:8788/api/watches"


def test_auth_token_is_sent_as_a_bearer_header(monkeypatch):
    monkeypatch.setenv("MAKI_AUTH_TOKEN", "s3cret")
    client = _client(payload={"watches": []})
    main(["watches"], client=client)
    assert client.get.call_args.kwargs["headers"] == {"Authorization": "Bearer s3cret"}


def test_no_auth_token_sends_no_header(monkeypatch):
    monkeypatch.delenv("MAKI_AUTH_TOKEN", raising=False)
    client = _client(payload={"watches": []})
    main(["watches"], client=client)
    assert client.get.call_args.kwargs["headers"] == {}

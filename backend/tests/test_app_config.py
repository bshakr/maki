from fastapi.testclient import TestClient

from maki.app_config.routes import ui_config_from
from maki.config import AppConfig
from maki.main import app
from maki.settings import settings


def _cfg(**overrides) -> AppConfig:
    base = {"aws": {"region": "us-east-1", "ecsCluster": "c"}}
    base.update(overrides)
    return AppConfig.model_validate(base)


def test_builder_applies_neutral_defaults():
    ui = ui_config_from(_cfg())
    assert ui.app_name == "Deploy Dashboard"
    assert ui.theme is None
    assert ui.env_label == "production"
    assert ui.aws_region == "us-east-1"
    assert ui.log_group_template == "/ecs/{service}-production"
    assert ui.amplify_enabled is False
    assert ui.grouping_rules == []
    assert ui.deploy_timeline_enabled is True
    assert ui.watches_enabled is settings.watch_enabled


def test_builder_reflects_the_watcher_kill_switch(monkeypatch):
    monkeypatch.setattr(settings, "watch_enabled", False)
    assert ui_config_from(_cfg()).watches_enabled is False


def test_builder_projects_theme_and_grouping():
    ui = ui_config_from(
        _cfg(
            branding={"appName": "Acme"},
            theme={"light": {"primary": "oklch(0.5 0.2 280)", "radius": "0.5rem"}},
            envLabel="prod",
            grouping={"rules": [{"match": "api-", "label": "API"}]},
            deployTimeline={"enabled": False},
        )
    )
    assert ui.app_name == "Acme"
    assert ui.theme is not None
    assert ui.theme.light["primary"] == "oklch(0.5 0.2 280)"
    assert ui.theme.light["radius"] == "0.5rem"
    assert ui.theme.dark == {}
    assert ui.env_label == "prod"
    assert ui.grouping_rules[0].match == "api-"
    assert ui.grouping_rules[0].label == "API"
    assert ui.deploy_timeline_enabled is False


def test_builder_omits_repo_map_and_secrets():
    # The UI response must not leak the repo map (backend-only). Confirm the field set is fixed.
    ui = ui_config_from(_cfg(github={"repos": [{"repo": "acme/x", "services": ["api"]}]}))
    assert "repos" not in ui.model_dump()
    assert "github" not in ui.model_dump()


def test_config_endpoint_returns_fixture_values():
    # Uses the suite's MAKI_CONFIG fixture (eu-west-1 / production / amplify enabled, no branding).
    client = TestClient(app)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["aws_region"] == "eu-west-1"
    assert body["amplify_enabled"] is True
    assert body["deploy_timeline_enabled"] is True
    assert body["watches_enabled"] is True
    assert body["app_name"] == "Deploy Dashboard"
    assert "repos" not in body


def test_config_reports_auth_not_required_by_default():
    client = TestClient(app)
    body = client.get("/api/config").json()
    assert body["auth_required"] is False

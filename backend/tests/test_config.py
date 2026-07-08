import textwrap

import pytest

from maki.config import AppConfig, ConfigError, load_config


def _write(tmp_path, body: str):
    path = tmp_path / "maki.config.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_missing_required_aws_field_raises_configerror(tmp_path):
    path = _write(
        tmp_path,
        """
        aws:
          region: us-east-1
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    msg = str(exc.value)
    assert "ecsCluster" in msg
    assert "maki.config.example.yaml" in msg


def test_missing_aws_block_raises_configerror(tmp_path):
    path = _write(tmp_path, "github:\n  repos: []\n")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "aws" in str(exc.value)


def test_missing_file_raises_friendly_configerror(tmp_path):
    path = tmp_path / "does-not-exist.yaml"
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    msg = str(exc.value)
    assert str(path) in msg
    assert "maki.config.example.yaml" in msg


def test_minimal_config_applies_all_defaults(tmp_path):
    path = _write(
        tmp_path,
        """
        aws:
          region: us-east-1
          ecsCluster: example-cluster
        """,
    )
    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)
    assert cfg.aws.region == "us-east-1"
    assert cfg.aws.ecsCluster == "example-cluster"
    assert cfg.aws.logGroupTemplate == "/ecs/{service}-production"
    assert cfg.github.repos == []
    assert cfg.amplify.enabled is False
    assert cfg.branding.appName == "Deploy Dashboard"
    assert cfg.theme is None
    assert cfg.envLabel == "production"
    assert cfg.grouping.rules == []
    assert cfg.deployTimeline.enabled is True
    assert cfg.deployTimeline.github.groupMatrixJobs is True
    assert cfg.deployTimeline.github.hideJobsStartingWith == ["deploy-"]
    assert cfg.deployTimeline.github.hideJobsEndingWith == ["deploy", "schedule"]
    assert cfg.repo_for("anything") is None


def test_full_config_round_trips(tmp_path):
    path = _write(
        tmp_path,
        """
        aws:
          region: eu-west-1
          ecsCluster: production
          logGroupTemplate: "/ecs/{service}-prod"
        github:
          repos:
            - repo: acme/platform
              services: [inventory, billing]
            - repo: acme/web
              services: [web-app]
        amplify:
          enabled: true
          appId: abc123
          branch: main
          serviceName: web-app
        branding:
          appName: Acme Deploys
        theme:
          light:
            primary: "oklch(0.52 0.24 280)"
            radius: "0.75rem"
          dark:
            primary: "oklch(0.62 0.22 280)"
        envLabel: prod
        grouping:
          rules:
            - { match: "wfm-", label: Workforce }
            - { match: "billing", label: Billing, exact: true }
        deployTimeline:
          enabled: false
          github:
            groupMatrixJobs: false
            hideJobsStartingWith: ["build-"]
            hideJobsEndingWith: ["release"]
        """,
    )
    cfg = load_config(path)
    assert cfg.aws.logGroupTemplate == "/ecs/{service}-prod"
    assert cfg.amplify.enabled is True
    assert cfg.amplify.appId == "abc123"
    assert cfg.amplify.serviceName == "web-app"
    assert cfg.branding.appName == "Acme Deploys"
    assert cfg.theme.light["primary"] == "oklch(0.52 0.24 280)"
    assert cfg.theme.light["radius"] == "0.75rem"
    assert cfg.theme.dark["primary"] == "oklch(0.62 0.22 280)"
    assert cfg.envLabel == "prod"
    assert cfg.grouping.rules[1].exact is True
    assert cfg.grouping.rules[1].label == "Billing"
    assert cfg.deployTimeline.enabled is False
    assert cfg.deployTimeline.github.groupMatrixJobs is False
    assert cfg.deployTimeline.github.hideJobsStartingWith == ["build-"]
    assert cfg.repo_for("inventory") == "acme/platform"
    assert cfg.repo_for("web-app") == "acme/web"
    assert cfg.repo_for("unmapped") is None


def test_unknown_theme_token_raises_configerror(tmp_path):
    path = _write(
        tmp_path,
        """
        aws:
          region: us-east-1
          ecsCluster: c
        theme:
          light:
            primary: "oklch(0.5 0 0)"
            not-a-token: "oklch(0.5 0 0)"
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "not-a-token" in str(exc.value)


def test_known_theme_tokens_accepted(tmp_path):
    path = _write(
        tmp_path,
        """
        aws:
          region: us-east-1
          ecsCluster: c
        theme:
          light:
            background: "oklch(1 0 0)"
            sidebar-ring: "oklch(0.5 0 0)"
            chart-5: "oklch(0.5 0 0)"
            radius: "0.5rem"
        """,
    )
    cfg = load_config(path)
    assert cfg.theme.light["chart-5"] == "oklch(0.5 0 0)"


def test_duplicate_service_across_repos_raises_configerror(tmp_path):
    path = _write(
        tmp_path,
        """
        aws:
          region: us-east-1
          ecsCluster: c
        github:
          repos:
            - repo: acme/one
              services: [inventory]
            - repo: acme/two
              services: [inventory]
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "inventory" in str(exc.value)


def test_repo_for_returns_repo_and_none(tmp_path):
    path = _write(
        tmp_path,
        """
        aws:
          region: us-east-1
          ecsCluster: c
        github:
          repos:
            - repo: acme/platform
              services: [inventory, billing]
        """,
    )
    cfg = load_config(path)
    assert cfg.repo_for("inventory") == "acme/platform"
    assert cfg.repo_for("billing") == "acme/platform"
    assert cfg.repo_for("web-app") is None

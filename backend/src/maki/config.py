"""Ingested application config — the single seam between the generic engine and a deployment's
specifics.

maki ships neutral and reads everything deployment-specific from one YAML file
(``maki.config.yaml`` by default, overridable via the ``MAKI_CONFIG`` env var). Only ``aws.region``
and ``aws.ecsCluster`` are required — they point maki at real infrastructure and have no sensible
default. Everything else is optional with a neutral default, so a new user fills two lines and gets
a working dashboard.

Field names mirror the YAML keys verbatim (camelCase) so the file and the model read the same.
``load_config`` reformats pydantic/YAML failures into a ``ConfigError`` that names the offending
field and points at ``maki.config.example.yaml`` — never a raw traceback as UX.
"""

import os
from pathlib import Path

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

DEFAULT_CONFIG_FILENAME = "maki.config.yaml"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_FILENAME  # back-compat alias (bare cwd-relative filename)
_EXAMPLE = "maki.config.example.yaml"

# Repo root, anchored off this file's location rather than the cwd: backend/src/maki/config.py
# → parents[3] == the repo root. The config (maki.config.yaml) is shared between the backend and
# the frontend, so it lives there — not under backend/.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _default_config_path() -> Path:
    """Locate ``maki.config.yaml`` without requiring ``MAKI_CONFIG``.

    The config is shared with the frontend and lives at the repo root, but the backend is usually
    launched from ``backend/``. Search the cwd first (run from the repo root) and the repo root
    second (run from ``backend/``) so it's found either way. If neither exists, return the repo-root
    path so the not-found error names the canonical location.
    """
    for candidate in (Path.cwd() / DEFAULT_CONFIG_FILENAME, _REPO_ROOT / DEFAULT_CONFIG_FILENAME):
        if candidate.is_file():
            return candidate
    return _REPO_ROOT / DEFAULT_CONFIG_FILENAME


# Allowed shadcn/Tailwind-v4 design tokens for the theme override block. A key outside this set is
# almost certainly a typo; rejecting it (with the bad name) beats silently injecting dead CSS.
THEME_TOKENS = frozenset(
    {
        "background",
        "foreground",
        "card",
        "card-foreground",
        "popover",
        "popover-foreground",
        "primary",
        "primary-foreground",
        "secondary",
        "secondary-foreground",
        "muted",
        "muted-foreground",
        "accent",
        "accent-foreground",
        "destructive",
        "destructive-foreground",
        "border",
        "input",
        "ring",
        "radius",
        "chart-1",
        "chart-2",
        "chart-3",
        "chart-4",
        "chart-5",
        "sidebar",
        "sidebar-foreground",
        "sidebar-primary",
        "sidebar-primary-foreground",
        "sidebar-accent",
        "sidebar-accent-foreground",
        "sidebar-border",
        "sidebar-ring",
    }
)


class ConfigError(Exception):
    """Raised when the config file is missing, malformed, or fails validation. Carries a
    human-readable message intended to be shown verbatim to whoever is running maki."""


class _Strict(BaseModel):
    # extra="forbid" turns a typo'd key into a named error instead of silent no-op config.
    model_config = ConfigDict(extra="forbid")


class AwsConfig(_Strict):
    region: str
    ecsCluster: str
    # ``{service}`` is substituted with the service name. Authoritative log group still comes from
    # the task def at request time; this is the pre-fetch fallback convention.
    logGroupTemplate: str = "/ecs/{service}-production"


class RepoGroup(_Strict):
    repo: str
    services: list[str] = Field(default_factory=list)


class GithubConfig(_Strict):
    repos: list[RepoGroup] = Field(default_factory=list)


class AmplifyConfig(_Strict):
    enabled: bool = False
    appId: str | None = None
    branch: str = "master"
    serviceName: str = "web-app"


class BrandingConfig(_Strict):
    appName: str = "Deploy Dashboard"


class ThemeConfig(_Strict):
    light: dict[str, str] = Field(default_factory=dict)
    dark: dict[str, str] = Field(default_factory=dict)

    @field_validator("light", "dark")
    @classmethod
    def _known_tokens(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(k for k in value if k not in THEME_TOKENS)
        if unknown:
            raise ValueError(f"unknown theme token(s): {', '.join(unknown)}")
        return value


class GroupingRule(_Strict):
    match: str
    label: str
    exact: bool = False


class GroupingConfig(_Strict):
    rules: list[GroupingRule] = Field(default_factory=list)


class TimelineGithubConfig(_Strict):
    groupMatrixJobs: bool = True
    hideJobsStartingWith: list[str] = Field(default_factory=lambda: ["deploy-"])
    hideJobsEndingWith: list[str] = Field(default_factory=lambda: ["deploy", "schedule"])


class DeployTimelineConfig(_Strict):
    enabled: bool = True
    github: TimelineGithubConfig = Field(default_factory=TimelineGithubConfig)


class AppConfig(_Strict):
    aws: AwsConfig
    github: GithubConfig = Field(default_factory=GithubConfig)
    amplify: AmplifyConfig = Field(default_factory=AmplifyConfig)
    branding: BrandingConfig = Field(default_factory=BrandingConfig)
    theme: ThemeConfig | None = None
    envLabel: str = "production"
    grouping: GroupingConfig = Field(default_factory=GroupingConfig)
    deployTimeline: DeployTimelineConfig = Field(default_factory=DeployTimelineConfig)

    # service -> repo, built once after validation. A service deploys from exactly one repo.
    _repo_index: dict[str, str] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _index_repos(self) -> "AppConfig":
        index: dict[str, str] = {}
        for group in self.github.repos:
            for service in group.services:
                if service in index:
                    raise ValueError(
                        f'service "{service}" is listed under two repos: '
                        f"{index[service]} and {group.repo}"
                    )
                index[service] = group.repo
        self._repo_index = index
        return self

    def repo_for(self, service_name: str) -> str | None:
        """The repo a service deploys from, or None if unmapped (enrichment is then skipped)."""
        return self._repo_index.get(service_name)


def _format_validation_error(path: Path, error: ValidationError) -> str:
    lines = [f"{path}: invalid config (see {_EXAMPLE}):"]
    for err in error.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "(root)"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    """Load + validate the config file. Raises ConfigError with a friendly message on failure."""
    if path is not None:
        resolved = Path(path)
    elif os.environ.get("MAKI_CONFIG"):
        resolved = Path(os.environ["MAKI_CONFIG"])
    else:
        resolved = _default_config_path()
    if not resolved.is_file():
        raise ConfigError(
            f"config file not found: {resolved} — copy {_EXAMPLE} to {resolved} and fill it in"
        )
    try:
        data = yaml.safe_load(resolved.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{resolved}: invalid YAML — {exc} (see {_EXAMPLE})") from exc
    if data is None or not isinstance(data, dict):
        raise ConfigError(f"{resolved}: top-level config must be a mapping (see {_EXAMPLE})")
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(resolved, exc)) from exc

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from maki.config import AppConfig, load_config

# The ingested config is loaded lazily on first access (not at import) so importing the app never
# requires a config file — only code paths that actually read deployment-specifics do. Cached for
# the process lifetime.
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


class Settings(BaseSettings):
    """Operational settings (env / .env) plus a thin façade over the ingested ``maki.config.yaml``.

    Operational knobs (DB, caches, ingester, GitHub token) live here as env-overridable fields.
    Deployment-specifics (AWS region/cluster, Amplify, repo mapping, timeline tuning) come from the
    YAML config and are exposed as properties under their long-standing names so call sites are
    unchanged.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    swr_fresh_seconds: float = 10.0  # serve cached as-is within this window
    swr_stale_seconds: float = 300.0  # serve stale + background refresh up to this bound
    static_dir: str | None = None  # set when serving the built SPA; unset in dev

    # maki's OWN dedicated Postgres. Port 5544 locally to avoid clashing with any existing Postgres
    # on 5432. Env-overridable via DATABASE_URL.
    database_url: str = "postgresql+psycopg://maki:maki@localhost:5544/maki"

    github_token: str | None = None  # auto-reads env GITHUB_TOKEN
    github_api_url: str = "https://api.github.com"

    # Background ingester for the deploy-events store. Disabled in tests/imports; the loop only
    # starts when an ASGI server actually runs the FastAPI lifespan.
    ingest_enabled: bool = True
    ingest_interval_seconds: float = 300.0  # one ingest cycle every 5 minutes
    ingest_backfill_days: int = 90  # cold-start window (bounded by ECS ~90d retention)
    ingest_overlap_seconds: int = 3600  # re-read this slice past the watermark each cycle
    ingest_max_revisions_per_service: int = 1000  # safety cap on per-service fan-out

    # Deploy notifications for watched services. A non-macOS host degrades to a no-op notifier
    # regardless of this flag.
    notify_enabled: bool = Field(default=True, validation_alias="MAKI_NOTIFY_ENABLED")

    # The watcher polls far more often than the ingester so a deploy is announced while it still
    # matters; the lookback bounds how far back a cycle scans for ECS rollouts and CI failures.
    watch_enabled: bool = True
    watch_interval_seconds: float = 45.0
    watch_lookback_minutes: int = 120

    # --- Security posture (env-only; never in config.yaml, never served to the SPA) ---
    # Optional shared bearer token. Unset/empty → auth disabled (the laptop default). Aliased so the
    # env var is the explicit MAKI_AUTH_TOKEN, not the bare field name.
    auth_token: str | None = Field(default=None, validation_alias="MAKI_AUTH_TOKEN")
    # Opt-in to bind a non-loopback interface (the launcher's bind guard checks this).
    allow_network_bind: bool = Field(default=False, validation_alias="MAKI_ALLOW_NETWORK_BIND")
    # Extra Host-header values to allow beyond loopback (comma-separated), for a reverse-proxy host.
    allowed_hosts: str = Field(default="", validation_alias="MAKI_ALLOWED_HOSTS")

    # --- Deployment-specifics, sourced from the ingested config (maki.config.yaml) ---

    @property
    def config(self) -> AppConfig:
        return get_config()

    @property
    def aws_region(self) -> str:
        return self.config.aws.region

    @property
    def ecs_cluster(self) -> str:
        return self.config.aws.ecsCluster

    @property
    def amplify_enabled(self) -> bool:
        return self.config.amplify.enabled

    @property
    def amplify_app_id(self) -> str | None:
        return self.config.amplify.appId

    @property
    def amplify_branch(self) -> str:
        return self.config.amplify.branch

    @property
    def amplify_service_name(self) -> str:
        return self.config.amplify.serviceName

    @property
    def timeline_rollout_job_suffixes(self) -> tuple[str, ...]:
        return tuple(self.config.deployTimeline.github.hideJobsEndingWith)

    def repo_for(self, service_name: str) -> str | None:
        return self.config.repo_for(service_name)

    @property
    def auth_required(self) -> bool:
        """True when a bearer token is configured, i.e. the SPA must present one."""
        return bool(self.auth_token)

    @property
    def trusted_hosts(self) -> list[str]:
        """Allowed Host-header values: loopback always, plus any from MAKI_ALLOWED_HOSTS."""
        extra = [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]
        return ["localhost", "127.0.0.1", "[::1]", *extra]


settings = Settings()
